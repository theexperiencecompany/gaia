---
name: googledrive-manage-files
description: Find, organize, share, download, and export files in Google Drive, including handing a file to Gmail as an attachment.
target: googledrive_agent
---

# Google Drive: Find, Share, and Attach Files

## When to Use
- User wants to find a file or folder in Drive
- User wants to share a file or folder with someone
- User wants to save content to Drive or organize files
- User wants a Drive file attached to an email

## Core Tools
- `GOOGLEDRIVE_FIND_FILE` — the canonical search. Resolve a name/description to a concrete file ID before doing anything else.
- `GOOGLEDRIVE_FIND_FOLDER` / `GOOGLEDRIVE_CREATE_FOLDER` — locate or create folders.
- `GOOGLEDRIVE_GET_FILE_METADATA` — confirm `mimeType`, `parents`, and `trashed` before a destructive or sharing action.
- `GOOGLEDRIVE_CREATE_FILE_FROM_TEXT` / `GOOGLEDRIVE_UPLOAD_FILE` — put new content in Drive.
- `GOOGLEDRIVE_DOWNLOAD_FILE` — download a file (exports Google Workspace docs). The result includes a fetchable URL.
- `GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE` — export a Doc/Sheet/Slide to a specific format.
- `GOOGLEDRIVE_MOVE_FILE` / `GOOGLEDRIVE_COPY_FILE_ADVANCED` — reorganize or duplicate.
- `GOOGLEDRIVE_CREATE_PERMISSION` — share with a user/group at a role.
- `GOOGLEDRIVE_TRASH_FILE` — reversible delete (prefer this over a permanent delete).

## Rules
1. **Search before acting.** Never guess a file or folder ID. Find it, then act.
2. **Confirm before destructive or sharing actions.** Permanent deletes are irreversible and gated; prefer trashing. Confirm the recipient and role before creating a permission.
3. **Report the link.** After any create/move/share, give the user the file name and its Drive link.

## Attaching a Drive file to an email
When the user wants a Drive file sent as an email attachment:
1. `GOOGLEDRIVE_FIND_FILE` to get the file ID.
2. `GOOGLEDRIVE_DOWNLOAD_FILE` (or export for a Workspace doc) to get a download URL.
3. Hand that URL to the Gmail draft as an attachment: the Gmail agent passes it as an attachment `url`. The draft is created with the file attached for the user to review before sending.
