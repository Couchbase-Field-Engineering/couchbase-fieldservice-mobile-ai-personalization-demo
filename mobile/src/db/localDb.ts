import type { Site, Catalog, ChatDoc, ContextDoc, WorkOrderRequest, Tech, WorkPlanDoc, SyncState } from '../types';

/**
 * The app's local database. Two implementations with the same contract:
 *
 * - `couchbase-lite` (cblDb.native.ts): the real thing. An on-device Couchbase
 *   Lite database (scope `field`, same collections as the server) kept in sync
 *   by a continuous push/pull replicator against Sync Gateway. Everything
 *   renders from here, so the app works with no connectivity at all.
 * - `preview` (previewDb.ts): a browser/Expo Go stand-in for demos without a
 *   device build - an in-memory store that polls the backend's REST
 *   `/api/sync/pull` and pushes work orders with `/api/sync/push`. Same document
 *   ids and shapes.
 */
export const SCOPE = 'field';
export const COLLECTIONS = ['sites', 'techs', 'work_plans', 'work_orders', 'assistant', 'context_cache', 'catalog'] as const;
export type CollectionName = (typeof COLLECTIONS)[number];

export const INTENTS = ['workplan', 'parts', 'alarms', 'outage', 'access', 'rma', 'budget', 'history', 'recurring', 'visit', 'general'];

export type Snapshot = {
  tech: Tech | null;
  /** Every site in the tech's area, by site_id. */
  sites: Record<string, Site>;
  /** Work plan per site_id. */
  plans: Record<string, WorkPlanDoc>;
  workOrders: WorkOrderRequest[];
  chat: ChatDoc | null;
  catalog: Catalog | null;
  /** Context cache docs by their id (ctx::<site>::<intent> / ctx::<tech>::runbook_<intent>). */
  contexts: Record<string, ContextDoc>;
};

export const EMPTY: Snapshot = { tech: null, sites: {}, plans: {}, workOrders: [], chat: null, catalog: null, contexts: {} };

export type SyncSession = {
  token: string;
  techId: string;
  sg: { session_id: string; cookie_name: string; url: string | null; db: string } | null;
};

export interface LocalDb {
  readonly engine: SyncState['engine'];
  open(techId: string): Promise<void>;
  read(): Promise<Snapshot>;
  saveRequest(req: WorkOrderRequest): Promise<void>;
  startSync(session: SyncSession): Promise<void>;
  setPaused(paused: boolean): Promise<void>;
  onChange(cb: () => void): () => void;
  onSyncState(cb: (s: SyncState) => void): () => void;
  location(): string | null;
  close(): Promise<void>;
}

export const ids = {
  tech: (r: string) => `tech::${r}`,
  site: (a: string) => `site::${a}`,
  plan: (a: string) => `plan::${a}`,
  chat: (r: string) => `chat::${r}`,
  ctx: (scope: string, k: string) => `ctx::${scope}::${k}`,
  catalog: 'catalog::v1',
};

export type Doc = Record<string, unknown> & { _id?: string };

/** Build a Snapshot from a by-id getter and a per-collection lister. */
export async function buildSnapshot(
  techId: string,
  get: (col: CollectionName, id: string) => Promise<Doc | null>,
  list: (col: CollectionName) => Promise<Doc[]>,
  workOrders: WorkOrderRequest[],
): Promise<Snapshot> {
  const sites: Record<string, Site> = {};
  for (const d of await list('sites')) {
    const a = d as unknown as Site;
    if (a.site_id) sites[a.site_id] = a;
  }
  const plans: Record<string, WorkPlanDoc> = {};
  for (const d of await list('work_plans')) {
    const s = d as unknown as WorkPlanDoc;
    if (s.site_id) plans[s.site_id] = s;
  }
  const contexts: Record<string, ContextDoc> = {};
  for (const d of await list('context_cache')) {
    const c = d as unknown as ContextDoc & { _id?: string };
    const key = c._id ?? ids.ctx(c.scope, c.personal ? c.intent : `runbook_${c.intent}`);
    contexts[key] = c;
  }
  return {
    tech: (await get('techs', ids.tech(techId))) as unknown as Tech | null,
    sites,
    plans,
    chat: (await get('assistant', ids.chat(techId))) as unknown as ChatDoc | null,
    catalog: (await get('catalog', ids.catalog)) as unknown as Catalog | null,
    contexts,
    workOrders: [...workOrders].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
  };
}

type Listener<T> = (v: T) => void;
export class Emitter<T> {
  private ls = new Set<Listener<T>>();
  on(l: Listener<T>) {
    this.ls.add(l);
    return () => {
      this.ls.delete(l);
    };
  }
  emit(v: T) {
    this.ls.forEach((l) => {
      try {
        l(v);
      } catch {
        /* listener errors never break sync */
      }
    });
  }
}
