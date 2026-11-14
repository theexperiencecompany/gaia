/**
 * The short-link target id of a file under a conversation's artifacts/ — the
 * same `<conversation_id>/<path>` shape the API's session_artifact_target_id builds.
 */
export function sessionArtifactTargetId(
  conversationId: string,
  path: string,
): string {
  return `${conversationId}/${path}`;
}
