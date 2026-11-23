/** "Connected as Name (@handle)", or plain "Connected" when the link names no one. */
export function connectedAsLabel(user: string | undefined): string {
  return user ? `Connected as ${user}` : "Connected";
}
