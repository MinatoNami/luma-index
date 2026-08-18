# PRD --- Self-Hosted Multi-User PDF Ebook Reader

## 1. Product Overview

**LumaIndex** is a self-hosted web application for browsing, organizing,
sharing, and reading PDF ebooks.

Users may create a normal application account without Google. Users who
connect Google Drive can import PDFs from their own Drive folders. Other
authenticated users can read books that owners explicitly share through
the application.

The application runs on an Ubuntu server and is accessed from desktop,
tablet, and mobile browsers, preferably through Tailscale.

Google Drive remains the source of truth for imported PDF files.
Django/PostgreSQL stores application identity, library metadata,
organization, sharing permissions, reading progress, bookmarks,
highlights, notes, and settings.

## 2. Core Product Principles

1.  **Django User is the canonical application identity.**
2.  **Google account is optional.**
3.  **Google Drive is an optional storage provider, not an identity
    requirement.**
4.  **Books are private by default.**
5.  **Shared books can be read by authenticated users without Google
    accounts.**
6.  **Reading progress, bookmarks, highlights, and notes are always
    per-user and private by default.**
7.  **Custom library organization must not modify the original Google
    Drive structure.**
8.  **Google Drive remains canonical storage for imported PDFs.**
9.  **Authorization must always be enforced by Django on the server.**

## 3. Goals

-   Support multiple users.
-   Support normal local application accounts.
-   Support Google sign-in/account linking.
-   Allow users to connect their own Google Drive.
-   Import PDFs recursively from selected Drive folders.
-   Preserve existing Google Drive folder hierarchy during import.
-   Allow independent custom folders/collections inside the application.
-   Provide a responsive PDF reader.
-   Synchronize reading state across devices.
-   Allow owners to share books with other authenticated users.
-   Allow non-Google users to read shared books.
-   Run through Docker Compose on Ubuntu.
-   Support private access through Tailscale.
-   Keep the architecture extensible for other storage providers, OCR,
    AI, and additional ebook formats.

## 4. Technology Stack

### Frontend

-   Nuxt 3
-   Vue 3
-   TypeScript
-   PDF.js

### Backend

-   Django
-   Django REST Framework (DRF)
-   django-allauth for account/social authentication where appropriate
-   PostgreSQL

### External Integration

-   Google OAuth
-   Google Drive API

### Deployment

-   Docker Compose
-   Ubuntu Server
-   Tailscale

### Optional Later

-   Celery
-   Redis
-   Dedicated document-processing workers

Do not introduce Celery/Redis until asynchronous workloads justify them.

## 5. High-Level Architecture

``` text
                    Google Drive
                         |
                  Google Drive API
                         |
                         v
                 ┌────────────────┐
                 │ Django Backend │
                 │                │
                 │ DRF API        │
                 │ Authentication │
                 │ Authorization  │
                 │ Drive Sync     │
                 │ Book Sharing   │
                 │ PDF Delivery   │
                 └───────┬────────┘
                         |
              ┌──────────┼───────────┐
              v          v           v
         PostgreSQL   PDF Cache   Thumbnails
              ^
              |
          REST API
              |
              v
          ┌────────┐
          │ Nuxt 3 │
          │ PDF.js │
          └────┬───┘
               |
           Tailscale
               |
       Desktop / Tablet / Mobile
```

## 6. Django Application Structure

Suggested backend organization:

``` text
backend/
├── config/
├── accounts/
├── integrations/
│   └── google_drive/
├── library/
├── reader/
├── sharing/
└── api/
```

### accounts

Responsible for:

-   Users
-   Authentication
-   Account linking
-   Roles
-   Sessions
-   Account management

### integrations/google_drive

Responsible for:

-   Google OAuth authorization
-   Drive connections
-   Drive folder selection
-   Drive synchronization
-   Token management

### library

Responsible for:

-   Books
-   Book sources
-   Collections
-   Metadata
-   Library browsing

### reader

Responsible for:

-   Reading progress
-   Bookmarks
-   Highlights
-   Notes
-   Reader preferences

### sharing

Responsible for:

-   Book visibility
-   Shared library
-   Access-control rules

### api

DRF routing/serialization and API composition where appropriate.

Avoid unnecessary coupling between Django apps.

## 7. User Authentication

Users must be able to create an account without Google.

### Required Login Methods

MVP:

-   Email/password
-   Google sign-in

Both authentication methods must resolve to a Django user.

### Account Linking

A Django user may optionally link a Google identity.

Example:

``` text
Django User
├── email/password
├── optional Google identity
└── optional Google Drive connection
```

Signing in with Google must not make Google Drive access mandatory.

### Sessions

Use secure Django-backed authentication/session handling suitable for a
Nuxt frontend.

Requirements:

-   Secure session cookies.
-   Logout.
-   Session expiration.
-   CSRF protection where applicable.
-   Password reset.
-   Password change.
-   Disabled-account handling.

Avoid storing authentication tokens in browser localStorage where secure
HTTP-only cookie-based authentication is practical.

## 8. Roles

Minimum roles:

### User

Can:

-   Manage their own account.
-   Connect Google Drive.
-   Import/manage their own books.
-   Create collections.
-   Read permitted books.
-   Share owned books.
-   Manage their own reading data.

### Admin

Can:

-   Manage users.
-   Disable/enable accounts.
-   Inspect sync failures.
-   Manage instance configuration.
-   View cache/storage status.

Admin status should not automatically expose private user annotations
through the normal application UI.

## 9. Google Drive Connections

Google Drive is optional.

A user without Google Drive can still use the application and read
shared books.

Users with Google Drive can connect their account and select one or more
root folders.

### Store

-   Google account/provider identifier
-   Drive connection status
-   encrypted OAuth refresh token
-   selected root folders
-   last synchronization time

### Security

OAuth tokens must:

-   Be encrypted at rest.
-   Never be returned to other users.
-   Never be logged.
-   Never be exposed to Nuxt after authorization unless absolutely
    required by the OAuth flow.

Use the least-privileged Google Drive scope that supports the required
folder-selection and recursive-reading workflow.

OAuth scope choice must be validated early because broader Drive scopes
can introduce additional Google verification/security requirements.

## 10. Google Drive Import

Users select one or more Drive folders containing PDFs.

The backend recursively discovers PDFs.

Preserve:

-   Drive file ID
-   Parent folder ID
-   Original path
-   Filename
-   MIME type
-   File size
-   Modified timestamp

Example:

``` text
Google Drive

Books/
├── Programming/
│   ├── Python/
│   │   └── Fluent Python.pdf
│   └── Architecture/
│       └── DDIA.pdf
└── Fiction/
    └── Dune.pdf
```

The initial application library may mirror this hierarchy.

## 11. Drive vs Application Organization

Google Drive folders represent physical/source organization.

Application collections represent logical organization.

They must be independent after import.

Example:

``` text
Google Drive source:

Books/Programming/Architecture/DDIA.pdf

Application collections:

Currently Reading/
    DDIA

Software Engineering/
    DDIA

Favourites/
    DDIA
```

The same book may exist in multiple application collections without
duplicating the PDF.

Moving a book between collections must never move the original Drive
file.

## 12. Collections

Users can:

-   Create collections.
-   Rename collections.
-   Delete collections.
-   Nest collections.
-   Add books.
-   Remove books.
-   Put one book into multiple collections.
-   Reorganize collections independently from Drive.

Suggested model:

``` text
Collection
- id
- user
- name
- parent
- created_at
- updated_at
```

Use a many-to-many relationship between books and collections.

Provide standard virtual/system views such as:

-   Continue Reading
-   Recently Added
-   Recently Opened
-   Favourites
-   Shared With Me
-   Unsorted/Inbox

## 13. Drive Synchronization

### Initial Sync

1.  Scan selected root folders.
2.  Discover PDFs recursively.
3.  Create book/source records.
4.  Record Drive hierarchy.
5.  Generate thumbnails.
6.  Optionally create matching initial collections.

### Subsequent Sync

Detect:

-   New PDFs
-   Deleted PDFs
-   Renamed PDFs
-   Moved PDFs
-   Modified PDFs
-   Permission changes

A temporarily unavailable Drive file must not cause annotations or
reading state to be deleted.

Mark unavailable sources appropriately.

### Sync Methods

MVP:

-   Manual refresh.
-   Optional scheduled periodic sync.

Later:

-   Google Drive change notifications/incremental synchronization.

## 14. Book Model

Separate logical books from storage sources.

``` text
Book
    |
    └── BookSource
            |
            └── Google Drive
```

This enables future storage providers:

``` text
BookSource
├── Google Drive
├── Local Upload
├── Dropbox
└── OneDrive
```

without redesigning the reader/library domain.

## 15. Library

Each user receives a personal library interface.

Required:

-   Grid view
-   List view
-   Cover/first-page thumbnail
-   Title
-   Filename
-   Owner where relevant
-   Original Drive path
-   Reading progress
-   Recently opened
-   Recently added
-   Search
-   Sort
-   Filters
-   Collections
-   Continue Reading
-   Favourites
-   Shared With Me

## 16. Book Sharing

Books are private by default.

MVP visibility:

``` text
PRIVATE
SHARED
```

### PRIVATE

Only the owner can access the book.

### SHARED

Any authenticated user on the instance may discover/read the book.

Future options may include:

``` text
PRIVATE
INSTANCE_SHARED
USER_SHARED
GROUP_SHARED
```

Do not implement complex ACLs for the MVP.

Sharing inside the application must not change Google Drive sharing
permissions.

## 17. Non-Google Users

A user without Google Drive must be able to:

-   Create/login to a Django account.
-   Browse books shared with the instance.
-   Read shared PDFs.
-   Maintain personal reading progress.
-   Create private bookmarks.
-   Create private highlights.
-   Create private notes.
-   Add accessible shared books to their own collections.
-   Configure reader preferences.

They cannot import their own Drive library until they connect Google
Drive.

## 18. Shared PDF Delivery

Shared readers must not require access to the owner's Google Drive.

PDF delivery must go through the Django authorization boundary.

Example:

``` text
Reader
   |
GET /api/books/{id}/content
   |
   v
Django
   |
   ├── authenticate user
   ├── check book permission
   ├── retrieve/validate cached PDF
   └── stream authorized content
           |
           v
        PDF.js
```

Django may fetch/cache the PDF using the owner's Drive connection.

Never expose the owner's Drive credentials to readers.

## 19. Per-User Reading State

Sharing a book does not share reading state.

Example:

``` text
Book: DDIA
Owner: Alice

Alice progress: 75%
Bob progress: 21%
Carol progress: 48%
```

The following are user-specific:

-   Reading progress
-   Bookmarks
-   Highlights
-   Notes
-   Reader settings
-   Personal collection membership where applicable

Annotations are private by default.

## 20. PDF Reader

Use PDF.js.

Required functionality:

-   Continuous scrolling
-   Single-page mode
-   Previous/next page
-   Jump to page
-   Current page / total pages
-   Reading percentage
-   Zoom
-   Fit width
-   Fit page
-   Fullscreen
-   Page thumbnails
-   PDF outline/table of contents where available
-   Text selection
-   Search within PDF
-   Keyboard navigation
-   Touch/mobile navigation
-   Restore reading position

## 21. Reading Progress

Automatically persist:

-   Current page
-   Scroll position where relevant
-   Reading percentage
-   Last opened timestamp
-   Updated timestamp

Updates should be throttled/debounced to avoid excessive database
writes.

Opening a book on another device should resume from the latest stored
position.

## 22. Bookmarks

Users can:

-   Bookmark pages.
-   Add optional labels.
-   View bookmarks.
-   Jump to bookmarks.
-   Remove bookmarks.

Bookmarks are private to the user.

## 23. Highlights and Notes

Users can:

-   Select PDF text.
-   Highlight selected text.
-   Attach notes.
-   Edit notes.
-   View highlights.
-   Jump to highlighted locations.
-   Delete highlights.

Store positions independently from viewport pixels so highlights survive
zoom and screen-size changes.

Do not modify the original PDF.

## 24. Reader Preferences

Persist per user:

-   Light/dark UI
-   View mode
-   Zoom
-   Fit width/fit page
-   Sidebar preference
-   Other reader settings

Settings should follow the user across devices.

## 25. PDF Cache

Google Drive remains canonical storage.

Django may maintain a server-side PDF cache.

``` text
First read:

Google Drive
    ↓
Django
    ↓
PDF cache
    ↓
Reader

Later read:

PDF cache
    ↓
Django authorization
    ↓
Reader
```

Requirements:

-   Cache using stable source/file identifiers.
-   Never trust filenames as unique identifiers.
-   Check authorization before serving cached content.
-   Validate cached copies against Drive modification metadata.
-   Invalidate stale copies.
-   Configure maximum cache size.
-   Support automatic cleanup.
-   Never expose the cache directory as an unrestricted static
    directory.

## 26. Large PDF Performance

Consider from the beginning:

-   Lazy page rendering.
-   Render only visible/near-visible pages.
-   Lazy thumbnails.
-   Avoid retaining every page canvas.
-   Cancel obsolete rendering operations.
-   HTTP range requests where feasible.
-   Memory usage on mobile/tablet.
-   Large-file streaming.

Test with realistically large PDF books before declaring the reader
production-ready.

## 27. Scanned PDFs

PDFs may not contain a text layer.

MVP:

-   Render scanned PDFs normally.
-   Search/highlighting may be unavailable.
-   Detect/tolerate missing text.
-   Inform the user when searchable text is unavailable.

OCR is deferred.

## 28. Core Database Entities

### User

Use a custom Django user model from the beginning.

Suggested fields:

-   id
-   email
-   display_name
-   role
-   is_active
-   created_at
-   updated_at

Prefer email as the primary login identifier.

### DriveConnection

-   id
-   user
-   provider_account_id
-   encrypted_refresh_token
-   status
-   created_at
-   updated_at

### DriveRoot

-   id
-   drive_connection
-   provider_folder_id
-   name
-   sync_enabled
-   last_synced_at

### Book

-   id
-   owner
-   title
-   page_count
-   visibility
-   thumbnail_path
-   created_at
-   updated_at

### BookSource

-   id
-   book
-   drive_connection
-   provider
-   provider_file_id
-   provider_parent_id
-   original_path
-   filename
-   mime_type
-   file_size
-   provider_modified_at
-   availability_status
-   created_at
-   updated_at

### Collection

-   id
-   user
-   name
-   parent
-   created_at
-   updated_at

### CollectionBook

-   collection
-   book

### ReadingProgress

-   user
-   book
-   page
-   scroll_position
-   percentage
-   last_opened_at
-   updated_at

Unique constraint:

``` text
(user, book)
```

### Bookmark

-   id
-   user
-   book
-   page
-   label
-   created_at

### Highlight

-   id
-   user
-   book
-   page
-   selected_text
-   position_data
-   note
-   created_at
-   updated_at

### UserSettings

-   user
-   theme
-   reader_mode
-   zoom
-   preferences

## 29. Authorization

Authorization must be enforced server-side in Django/DRF.

Never rely solely on Nuxt hiding UI elements.

Examples:

``` text
Private book:

book.owner == request.user

Shared book:

book.owner == request.user
OR
book.visibility == SHARED

Progress:

progress.user == request.user

Bookmark:

bookmark.user == request.user

Highlight:

highlight.user == request.user

Collection:

collection.user == request.user
```

Object-level permissions must apply to:

-   API endpoints
-   PDF streaming
-   Cache access
-   thumbnails where necessary
-   modifications
-   sharing actions

## 30. API Design

Use REST through Django REST Framework.

Suggested namespaces:

``` text
/api/auth/
/api/users/
/api/drive/
/api/library/
/api/books/
/api/collections/
/api/reader/
/api/shared/
```

Examples:

``` text
GET    /api/books/
GET    /api/books/{id}/
GET    /api/books/{id}/content
PATCH  /api/books/{id}/

GET    /api/books/{id}/progress
PUT    /api/books/{id}/progress

GET    /api/books/{id}/bookmarks
POST   /api/books/{id}/bookmarks

GET    /api/books/{id}/highlights
POST   /api/books/{id}/highlights

GET    /api/collections/
POST   /api/collections/

GET    /api/shared/books/

POST   /api/drive/connect/
POST   /api/drive/sync/
```

Exact endpoint structure may evolve during implementation.

## 31. API Documentation

Generate an OpenAPI schema for the DRF API.

Provide browsable API documentation in development.

This makes frontend/backend integration and future external clients
easier.

## 32. Security

Required:

-   HTTPS where practical.
-   Secure cookies.
-   HttpOnly authentication/session cookies.
-   Appropriate SameSite policy.
-   CSRF protection.
-   Strong password hashing through Django.
-   OAuth token encryption at rest.
-   Never log credentials/tokens.
-   Server-side object authorization.
-   Input validation.
-   File ID validation.
-   Authentication rate limiting where appropriate.
-   Dependency updates.
-   Non-root containers where practical.
-   Environment/Docker secrets.
-   Database backups.
-   Secure production Django settings.
-   `DEBUG=False` in production.
-   Restrictive `ALLOWED_HOSTS`.
-   Correct trusted-origin configuration.

## 33. Privacy and Account Lifecycle

Users must be able to:

-   Disconnect Google Drive.
-   Remove their indexed library.
-   Delete reading progress.
-   Delete bookmarks.
-   Delete highlights/notes.
-   Delete their application account.

Disconnecting Drive must not automatically destroy annotations unless
explicitly requested.

Deleting cached PDFs must never delete source files from Drive.

Account deletion must define what happens to books previously shared by
that user.

Recommended MVP behavior:

-   Disable/remove access to the user's shared books when the owner
    account/library is deleted.
-   Remove cached copies according to retention policy.

## 34. Django Admin

Use Django Admin as the initial operational/admin interface.

Admin should expose appropriate management views for:

-   Users
-   Books
-   Book sources
-   Drive connections
-   Drive roots
-   Collections
-   Sync status
-   Shared books

Sensitive fields such as OAuth refresh tokens must never be displayed in
plaintext.

Custom end-user administration UI can be built later if needed.

## 35. Error Handling

Handle:

-   Invalid credentials.
-   Disabled account.
-   Google OAuth revoked.
-   Expired Drive authorization.
-   Drive API unavailable.
-   Drive file deleted.
-   Drive file moved/renamed.
-   Drive permissions removed.
-   Corrupt PDF.
-   Password-protected/encrypted PDF.
-   Network failure.
-   Database failure.
-   Cache failure.
-   Synchronization failure.

Failures must not unnecessarily destroy reader metadata.

## 36. Background Processing

Do not require Celery for the first implementation.

Simple/small sync operations may run synchronously or through
lightweight application mechanisms.

Introduce Celery + Redis when needed for:

-   Large Drive synchronization.
-   Thumbnail generation.
-   OCR.
-   Metadata extraction.
-   AI indexing.
-   Long-running document processing.

The domain architecture should allow these operations to move into
background jobs later.

## 37. Deployment

Docker Compose services initially:

``` text
frontend
backend
postgres
```

Example:

``` text
Ubuntu Server
│
├── Nuxt
├── Django + DRF
├── PostgreSQL
└── persistent volumes
    ├── postgres-data
    ├── pdf-cache
    └── thumbnails
```

Provide:

-   `docker-compose.yml`
-   `.env.example`
-   migrations
-   health checks
-   restart policies
-   documented initial setup
-   documented upgrade process
-   backup/restore instructions

Access initially through Tailscale.

Do not require public internet exposure beyond outbound access needed
for Google APIs/OAuth.

## 38. Backups

PostgreSQL contains irreplaceable application data.

Back up:

-   Users
-   Library metadata
-   Collections
-   Sharing settings
-   Reading progress
-   Bookmarks
-   Highlights
-   Notes
-   Settings

PDF cache and thumbnails are disposable/regenerable and do not need
normal backups.

Google OAuth credentials should be handled according to the chosen
secure backup strategy.

## 39. Responsive Design

Support:

-   Desktop
-   Laptop
-   Tablet
-   Mobile

Tablet is a primary reading target.

Reader UX priorities:

-   Large reading area.
-   Minimal distraction.
-   Touch-friendly controls.
-   Easy page navigation.
-   Fast return to library.
-   Responsive sidebars/toolbars.

## 40. Accessibility

Include:

-   Keyboard navigation.
-   Visible focus states.
-   Semantic control labels.
-   Sufficient contrast.
-   Touch targets suitable for mobile/tablet.
-   No hover-only critical interactions.
-   Reduced-motion support where appropriate.

## 41. Observability

MVP:

-   Structured Django logs.
-   Authentication failure logs without credentials.
-   Drive synchronization logs.
-   PDF processing errors.
-   Application health endpoint.
-   Database health checks.
-   Cache/disk usage visibility.

Avoid introducing a complex observability stack initially.

## 42. Non-Goals for MVP

Do not initially implement:

-   EPUB
-   MOBI/AZW
-   DRM circumvention/support
-   OCR
-   AI features
-   Semantic/vector search
-   Audiobooks
-   Anonymous/public reading
-   Public registration unless explicitly enabled
-   Complex sharing ACLs
-   Groups
-   PDF editing
-   Drive folder modification
-   Dropbox
-   OneDrive
-   Native mobile applications

## 43. Future Features

Potential future additions:

-   PWA/offline reading
-   OCR
-   EPUB
-   CBZ/CBR
-   Reading statistics
-   Reading goals/streaks
-   Tags
-   Ratings
-   Metadata editing
-   Automatic metadata lookup
-   Duplicate detection
-   Global highlight search
-   Dictionary
-   Translation
-   Text-to-speech
-   Local PDF uploads
-   Dropbox
-   OneDrive
-   Explicit user-to-user sharing
-   Shared collections
-   Groups
-   Annotation sharing
-   Annotation export/import
-   AI book Q&A
-   Summarization
-   Semantic search
-   Cross-book knowledge search
-   pgvector
-   Celery/Redis processing pipeline

## 44. Suggested Implementation Phases

### Phase 1 --- Platform Foundation

-   Docker Compose
-   PostgreSQL
-   Django
-   DRF
-   Custom User model
-   Nuxt
-   Authentication
-   Django Admin
-   Tailscale deployment

### Phase 2 --- Google Drive

-   Google account linking
-   Drive OAuth
-   Drive connection model
-   Root folder selection
-   Recursive PDF discovery
-   Initial synchronization
-   PDF cache
-   Thumbnail generation

### Phase 3 --- Library

-   Library grid/list
-   Imported Drive hierarchy
-   Search
-   Sort
-   Filters
-   Custom nested collections
-   Favourites
-   Continue Reading
-   Unsorted

### Phase 4 --- PDF Reader

-   PDF.js
-   Navigation
-   Continuous/single-page modes
-   Zoom
-   Search
-   Table of contents
-   Thumbnails
-   Reader preferences
-   Progress synchronization

### Phase 5 --- Reading Data

-   Bookmarks
-   Highlights
-   Notes

### Phase 6 --- Sharing

-   Private/shared visibility
-   Shared Library
-   Non-Google reader access
-   Authorized Django PDF streaming
-   Per-user reading state for shared books

### Phase 7 --- Hardening

-   Security review
-   Object-level permission tests
-   OAuth failure handling
-   Drive resync/recovery
-   Cache limits/cleanup
-   Large-PDF testing
-   Backups
-   Restore testing
-   Mobile/tablet UX testing

## 45. MVP Success Criteria

The MVP is complete when:

1.  The application runs through Docker Compose on Ubuntu.
2.  Users can access it through Tailscale.
3.  Users can register/login with a normal application account.
4.  Users can optionally sign in/link Google.
5.  A Django user exists independently of Google.
6.  A user can connect their Google Drive.
7.  A user can select one or more Drive book folders.
8.  PDFs are recursively discovered.
9.  Existing Drive hierarchy is preserved during import.
10. Users can create independent custom nested collections.
11. Reorganizing collections never changes Drive.
12. Users can read PDFs through PDF.js.
13. Reading progress synchronizes between devices.
14. PDF text search works when a text layer exists.
15. Users can create bookmarks.
16. Users can create highlights and notes.
17. Books are private by default.
18. Owners can share books with authenticated instance users.
19. Non-Google users can read shared books.
20. Shared readers never require access to the owner's Drive
    credentials.
21. Django authorizes every PDF-content request.
22. Each reader has independent progress/bookmarks/highlights/notes.
23. Users cannot access another user's private books.
24. Users cannot access another user's private annotations.
25. Drive authorization revocation is handled safely.
26. Deleted/unavailable Drive files do not automatically destroy reading
    metadata.
27. Cached PDFs cannot bypass Django authorization.
28. Large PDFs remain usable without excessive browser memory usage.
29. Application database backups can be created and restored.
30. Django Admin provides basic operational management.
31. The DRF API exposes an OpenAPI schema/documentation.
