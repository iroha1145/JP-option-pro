import type { AccessStatus } from '../api/types.ts';

/** 自选接口优先读取客户会话；所有者权限仍由 is_owner 单独决定。 */
export function accessIdentity(status: AccessStatus | null): string {
  if (!status) return 'unknown';
  if (status.account?.logged_in) return `account:${status.account.username ?? ''}`;
  return status.is_owner ? 'owner' : 'visitor';
}
