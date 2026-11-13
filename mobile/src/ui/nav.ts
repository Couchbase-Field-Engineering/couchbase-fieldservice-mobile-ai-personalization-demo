import { router } from 'expo-router';
import type { SuggestedAction } from '../types';
import type { IconName } from './components';

export const TOOL_LABEL: Record<string, string> = {
  submit_work_order: 'Work order',
  request_budget_override: 'Budget override',
  set_recurring_task: 'Recurring task',
  create_rma: 'RMA',
  log_site_visit: 'Visit log',
  request_outage_window: 'Outage window',
};

export const TOOL_ICON: Record<string, IconName> = {
  submit_work_order: 'construct',
  request_budget_override: 'shield-checkmark',
  set_recurring_task: 'repeat',
  create_rma: 'return-down-back',
  log_site_visit: 'location',
  request_outage_window: 'power',
};

const SCREENS: Record<string, string> = { route: '/(tabs)', sites: '/(tabs)/sites', assistant: '/(tabs)/assistant', workorders: '/(tabs)/workorders' };

/** Open the screen behind an assistant suggestion or a card CTA. */
export function openAction(a: SuggestedAction, title?: string) {
  if (a.screen) {
    const pathname = SCREENS[a.screen] ?? `/${a.screen}`;
    router.push({ pathname: pathname as never, params: Object.fromEntries(Object.entries(a.args ?? {}).map(([k, v]) => [k, String(v)])) });
    return;
  }
  if (a.tool) {
    router.push({
      pathname: '/confirm',
      params: { tool: a.tool, args: JSON.stringify(a.args ?? {}), title: title ?? a.label },
    });
  }
}
