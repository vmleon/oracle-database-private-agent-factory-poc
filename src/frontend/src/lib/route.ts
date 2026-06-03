/** True when the current path is the backoffice reviewer app (vs. the customer app). */
export function isBackofficePath(pathname: string): boolean {
  return pathname === "/backoffice" || pathname.startsWith("/backoffice/");
}
