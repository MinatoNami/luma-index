# Google OAuth and Drive scopes

Read this before Phase 2. The scope decision has consequences that are painful
to reverse and are not obvious from the API docs.

## The problem in one paragraph

LumaIndex wants to walk a user's chosen Drive folders and read every PDF inside
them. The scope that straightforwardly allows this — `drive.readonly` — is one
of Google's **restricted** scopes. Restricted scopes require OAuth verification
*and* an annual third-party security assessment (CASA) before an app can be
published. That assessment is priced for companies, not for a self-hosted
reader serving a household.

## The three viable routes

### 1. Stay in "Testing" mode (simplest, has a sharp edge)

Leave the OAuth consent screen in **Testing** and add each user as a test user
(up to 100). No verification, no assessment, `drive.readonly` works.

The edge: **refresh tokens issued by an app in Testing mode expire after 7
days.** Sync silently stops working roughly weekly and every user has to
reconnect Drive. This is the single most common surprise when self-hosting
against the Drive API.

If you take this route, treat it as a known limitation and build for it:

- Store an explicit `DriveConnection.status`, and set it to `expired` the
  moment a refresh returns `invalid_grant`.
- Surface "Reconnect Google Drive" in the UI instead of failing a sync silently.
- Never delete books, reading progress, or annotations when a token expires —
  PRD §13 and §35 both require this, and a 7-day expiry makes it a weekly test
  of whether you got it right.

### 2. Internal app on Google Workspace (best, if you have Workspace)

If the tailnet's users are all in one Google Workspace domain, set the consent
screen's user type to **Internal**. Verification does not apply, restricted
scopes are allowed, and refresh tokens do not expire on a 7-day timer.

This is the right answer whenever it is available.

### 3. `drive.file` + Google Picker (no verification, different UX)

`drive.file` is a non-sensitive scope: the app only ever sees files the user
explicitly hands it through the Google Picker. No verification, no assessment,
no 7-day expiry.

The cost is that the PRD's "select a root folder, discover PDFs recursively"
flow changes shape — the user grants access through the Picker rather than the
app enumerating Drive on its own. **Validate exactly what folder selection
grants under `drive.file` against the current API before committing to it**;
this behaviour has changed more than once, and the answer determines whether
PRD §10's recursive import is achievable on this scope.

## Recommendation

Prototype on route 1 to get Phase 2 working, and decide between 2 and 3 before
anyone else depends on the instance. PRD §9 already says the scope choice must
be validated early — this is what that validation looks like in practice.

## Other Drive API details worth knowing up front

| Concern | What to do |
| --- | --- |
| Shared drives | Pass `supportsAllDrives=true` and `includeItemsFromAllDrives=true` on list calls, or files in Shared Drives are invisible. |
| Shortcuts | `application/vnd.google-apps.shortcut` entries point at a PDF elsewhere. Resolve `shortcutDetails.targetId` or you will import broken records. |
| Google-native files | A Google Doc is not a PDF and needs `files.export`, not `files.get`. Filter on `mimeType='application/pdf'` and decide deliberately whether to export Docs later. |
| Change detection | Store a `startPageToken` per connection from day one. It costs nothing now and is the only way to do incremental sync later without re-listing everything. |
| Quotas | List calls are quota-metered per project and per user. Use `fields=` projections, page through with `pageToken`, and back off exponentially on 403 `userRateLimitExceeded`. |
| Rename vs move | Key everything on the immutable file ID. Path and name are display data — PRD §13 depends on this distinction. |
| Deleted files | A file that vanishes from a listing may be trashed, moved out of the selected root, or unshared. Mark the source unavailable; never cascade a delete into reading state. |

## Redirect URI

`GOOGLE_OAUTH_REDIRECT_URI` must match the Google console entry byte for byte,
and must be reachable from the user's browser. On a Tailscale-only deployment
that means the MagicDNS name:

```
https://luma.your-tailnet.ts.net/api/drive/oauth/callback
```

Google requires HTTPS for non-localhost redirect URIs, which is another reason
the deployment terminates TLS with `tailscale serve` rather than serving plain
HTTP.
