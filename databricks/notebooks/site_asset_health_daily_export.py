# Databricks notebook source
# MAGIC %md
# MAGIC # Site asset health - daily export for the telecom field service app
# MAGIC
# MAGIC Runs every morning (see `../jobs/site_asset_health_daily_export.job.json`, 04:30 America/New_York).
# MAGIC
# MAGIC 1. Join every on-air network site with Network 360 (SLA class, maintenance budget, contacts, access notes),
# MAGIC    its installed assets, open alarms, 30-day KPIs, the last 12 work orders, per-part wear and the visit schedule.
# MAGIC 2. Score every site with the registered asset-health model (`telco_asset_health`, alias `champion`):
# MAGIC    failure risk per equipment category, days-to-failure per component, recommended parts with a confidence each,
# MAGIC    upgrade candidates and 30-day outage risk.
# MAGIC 3. Write the Delta table `telco_prod.network360.site_asset_health_daily`.
# MAGIC 4. Export the same rows as JSON Lines to a Unity Catalog volume partitioned by `dt=`,
# MAGIC    with `_SUCCESS` and `_manifest.json` - the drop the demo backend's loader picks up and
# MAGIC    publishes to Couchbase (operational + Couchbase Lite sync) and the AOM Knowledge Base.
# MAGIC
# MAGIC **This is the only Databricks compute the app ever uses.** Every site read, work plan, parts lookup
# MAGIC and assistant answer during the day is served from Couchbase (or from Couchbase Lite on the
# MAGIC technician's phone), not from a SQL warehouse or a Model Serving endpoint. One scheduled job, once a day.
# MAGIC
# MAGIC In this repo the same output is produced locally by `databricks/generate_mock_dump.py`
# MAGIC (mock data, identical schema), so the demo runs without a Databricks workspace.

# COMMAND ----------

dbutils.widgets.text("catalog", "telco_prod")
dbutils.widgets.text("schema", "network360")
dbutils.widgets.text("export_volume", "/Volumes/telco_prod/network360/exports/site_asset_health_daily")
dbutils.widgets.text("history_work_orders", "12")
dbutils.widgets.text("num_files", "4")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
EXPORT = dbutils.widgets.get("export_volume")
HISTORY = int(dbutils.widgets.get("history_work_orders"))
NUM_FILES = int(dbutils.widgets.get("num_files"))
SCHEMA_VERSION = "site_asset_health_v1"

import datetime as dt
import json

from pyspark.sql import functions as F
from pyspark.sql import Window

export_date = dt.date.today().isoformat()
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------
# MAGIC %md ## 1. On-air sites + Network 360

# COMMAND ----------

sites = spark.table("sites_current").where(F.col("status") == "On air")
areas = spark.table("field_areas").select("area_id", "area_name", "tech_id")
techs = spark.table("field_technicians").select("tech_id", "employee_id", "first_name", "last_name", "email", "certifications")
contacts = (
    spark.table("site_contacts").groupBy("site_id")
    .agg(F.collect_list(F.struct("name", "role", "phone", "email")).alias("contacts"))
)
sla = spark.table("site_sla")                              # tier, tier_name, restore_hours, pm_cadence_days, agreement_id, renewal_date, on_air_since
budget = spark.table("site_maintenance_budget")            # budget_limit_usd, committed_usd, period
holds = spark.table("site_access_holds")                   # hold_days, on_hold, hold_reason
access = spark.table("site_access_profile")                # access_hours, climb_required, access_notes, depot
visits = spark.table("field_visit_schedule")               # last_visit, cadence_days, next_visit_date, planned_time, signal_note, visit_notes
assets = (
    spark.table("installed_assets").groupBy("site_id")
    .agg(F.collect_list(F.struct("asset_id", "category", "name", "vendor", "installed", "health", "status")).alias("assets"))
)
alarms = (
    spark.table("fm_alarms_open").groupBy("site_id")       # fault-management feed, open alarms only
    .agg(F.collect_list(F.struct("alarm_id", "severity", "code", "text", "action", "category", "raised_at")).alias("alarms"))
)
kpis = spark.table("pm_site_kpis_30d")                     # availability_30d_pct, outage_min_30d, subscribers_served
work_orders = (
    spark.table("work_orders").join(spark.table("work_order_parts").groupBy("work_order_id").agg(
        F.collect_list(F.struct("sku", "name", "qty", "unit_cost", "line_total")).alias("lines"),
        F.count("*").alias("line_count")), "work_order_id")
    .withColumn("rn", F.row_number().over(Window.partitionBy("site_id").orderBy(F.desc("closed_date"))))
    .where(f"rn <= {HISTORY}")
    .groupBy("site_id")
    .agg(F.collect_list(F.struct(F.col("work_order_id"), F.col("closed_date").alias("date"), "status", "source", "work_type",
                                 "line_count", "lines", "parts_usd", "total_usd", "backordered")).alias("work_history"))
)
wear = spark.table("part_wear_by_site")                    # map<sku, struct<per_year, last_replaced, last_qty>>
maintenance = spark.table("site_maintenance_12m")          # last_12mo_usd, ytd_usd, avg_work_order_usd, work_orders_last_12mo, category_mix
recurring = spark.table("recurring_tasks_active")          # array<struct<sku,name,qty,unit_cost,cadence_weeks,next_date>>

base = (
    sites.join(areas, "area_id").join(techs, "tech_id")
    .join(contacts, "site_id", "left").join(sla, "site_id").join(budget, "site_id").join(holds, "site_id", "left")
    .join(access, "site_id").join(visits, "site_id").join(assets, "site_id", "left").join(alarms, "site_id", "left")
    .join(kpis, "site_id", "left").join(work_orders, "site_id", "left")
    .join(wear, "site_id", "left").join(maintenance, "site_id", "left").join(recurring, "site_id", "left")
)

# COMMAND ----------
# MAGIC %md ## 2. Score with the asset-health model

# COMMAND ----------

import mlflow

mlflow.set_registry_uri("databricks-uc")
model_uri = f"models:/{CATALOG}.ml.telco_asset_health@champion"
score_udf = mlflow.pyfunc.spark_udf(spark, model_uri, result_type="string")  # returns JSON of ml_scores
model_version = mlflow.MlflowClient().get_model_version_by_alias(f"{CATALOG}.ml.telco_asset_health", "champion").version

feature_cols = [c for c in base.columns if c not in ("contacts", "first_name", "last_name", "email")]
scored = base.withColumn("ml_scores_json", score_udf(F.struct(*feature_cols)))

# COMMAND ----------
# MAGIC %md ## 3. Shape to the export schema and write Delta

# COMMAND ----------

ml_schema = ("struct<model_version:string,scored_at:string,power_failure_risk:double,cooling_failure_risk:double,"
             "radio_failure_risk:double,antenna_failure_risk:double,transport_failure_risk:double,"
             "fiber_failure_risk:double,site_failure_risk:double,tooling_gap_score:double,"
             "outage_risk:double,predicted_parts_cost_usd:double,days_to_failure:map<string,int>,"
             "recommended_parts:array<struct<sku:string,qty:int,confidence:double,reason:string>>,"
             "upgrade_skus:array<string>,segment:string,next_best_action:string>")

out = scored.select(
    F.lit(export_date).alias("export_date"),
    F.lit(SCHEMA_VERSION).alias("schema_version"),
    "site_id", "site_name", "site_code", "site_type", "site_type_name",
    F.struct("cluster_id", "cluster_name", F.col("cluster_sites").alias("sites")).alias("cluster"),
    F.struct("street", "city", "state", "zip").alias("address"),
    "area_id", "area_name",
    F.struct("tech_id", "employee_id", "first_name", "last_name", "email", "certifications").alias("assigned_tech"),
    "contacts",
    F.struct("tier", "tier_name", "restore_hours", "pm_cadence_days", "agreement_id", "renewal_date", "on_air_since").alias("sla"),
    F.struct("budget_limit_usd", "committed_usd", "period", F.coalesce("hold_days", F.lit(0)).alias("hold_days"),
             F.coalesce("on_hold", F.lit(False)).alias("on_hold"), "hold_reason",
             F.lit(0.0).alias("temporary_extension_usd")).alias("auth"),
    F.struct("access_hours", "climb_required", F.col("access_notes").alias("notes"), "depot").alias("access"),
    F.struct("last_visit", "cadence_days", "next_visit_date", "planned_time", "signal_note",
             F.col("visit_notes").alias("notes")).alias("visit"),
    F.coalesce("assets", F.array()).alias("assets"),
    F.coalesce("alarms", F.array()).alias("alarms"),
    F.struct("availability_30d_pct", "outage_min_30d", "subscribers_served").alias("kpis"),
    "work_history", "wear",
    F.struct("last_12mo_usd", "ytd_usd", "avg_work_order_usd", "work_orders_last_12mo", "category_mix").alias("maintenance"),
    "recurring_tasks",
    F.from_json("ml_scores_json", ml_schema).alias("ml_scores"),
    F.struct("generator_backup", "shared_site").alias("flags"),
    F.struct(F.lit(f"{CATALOG}.{SCHEMA}.site_asset_health_daily").alias("source_table"),
             F.lit("site_asset_health_daily_export").alias("pipeline"),
             F.lit(spark.conf.get("spark.databricks.clusterUsageTags.sparkVersion", "")).alias("dbr_version"))
    .alias("_ingest"),
)

(out.write.format("delta").mode("overwrite").option("replaceWhere", f"export_date = '{export_date}'")
    .partitionBy("export_date").saveAsTable("site_asset_health_daily"))

# COMMAND ----------
# MAGIC %md ## 4. Export JSON Lines for the app (dt= partition + _SUCCESS + _manifest.json)

# COMMAND ----------

path = f"{EXPORT}/dt={export_date}"
daily = spark.table("site_asset_health_daily").where(F.col("export_date") == export_date)
daily.repartition(NUM_FILES).write.mode("overwrite").json(path)   # Spark writes part-*.json + _SUCCESS

files = [f for f in dbutils.fs.ls(path) if f.name.startswith("part-")]
manifest = {
    "table": f"{CATALOG}.{SCHEMA}.site_asset_health_daily",
    "export_date": export_date, "schema_version": SCHEMA_VERSION,
    "model_version": f"telco-asset-health-v{model_version}", "format": "jsonl",
    "rows": daily.count(), "areas": daily.select("area_id").distinct().count(),
    "bytes": sum(f.size for f in files), "files": [{"file": f.name, "bytes": f.size} for f in files],
}
dbutils.fs.put(f"{path}/_manifest.json", json.dumps(manifest, indent=2), overwrite=True)
print(json.dumps(manifest, indent=2))

# COMMAND ----------
# MAGIC %md
# MAGIC ## Delivery to the demo backend
# MAGIC The backend watches `DUMP_DIR` for a newer `dt=*/_SUCCESS`. Point it at wherever this volume lands:
# MAGIC * copy it down: `databricks fs cp -r dbfs:/Volumes/.../dt=<date> ./data/databricks-dump/dt=<date>`
# MAGIC * or mount the cloud storage location behind the volume into the backend container at `/data/databricks-dump`.
# MAGIC
# MAGIC After this job finishes, Databricks is done for the day: the warehouse can auto-stop.
