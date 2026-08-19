from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    path("folders/", views.FolderListView.as_view(), name="folders"),
    path("folders/<int:folder_id>/", views.FolderDetailView.as_view(), name="folder-detail"),
    path("folders/<int:folder_id>/restore/", views.FolderRestoreView.as_view(),
         name="folder-restore"),

    path("books/", views.BookListView.as_view(), name="books"),
    path("books/<int:book_id>/", views.BookDetailView.as_view(), name="book-detail"),
    path("books/<int:book_id>/restore/", views.BookRestoreView.as_view(), name="book-restore"),
    path("books/<int:book_id>/content", views.BookContentView.as_view(), name="book-content"),
    path("books/<int:book_id>/thumbnail", views.BookThumbnailView.as_view(),
         name="book-thumbnail"),
    path("books/<int:book_id>/outline", views.BookOutlineView.as_view(), name="book-outline"),
    path("books/<int:book_id>/progress", views.BookProgressView.as_view(),
         name="book-progress"),
    path("books/<int:book_id>/bookmarks", views.BookmarkListView.as_view(), name="bookmarks"),
    path("books/<int:book_id>/bookmarks/<int:annotation_id>", views.BookmarkDetailView.as_view(),
         name="bookmark-detail"),
    path("books/<int:book_id>/highlights", views.HighlightListView.as_view(), name="highlights"),
    path("books/<int:book_id>/highlights/<int:annotation_id>",
         views.HighlightDetailView.as_view(), name="highlight-detail"),
    path("books/<int:book_id>/notes", views.PageNoteListView.as_view(), name="notes"),
    path("books/<int:book_id>/notes/<int:annotation_id>", views.PageNoteDetailView.as_view(),
         name="note-detail"),

    path("books/<int:book_id>/share", views.BookShareView.as_view(), name="book-share"),
    path("shared/", views.SharedBooksView.as_view(), name="shared"),

    path("collections/", views.CollectionListView.as_view(), name="collections"),
    path("collections/<int:collection_id>/", views.CollectionDetailView.as_view(),
         name="collection-detail"),
    path("collections/<int:collection_id>/books/", views.CollectionBooksView.as_view(),
         name="collection-books"),
    path("collections/<int:collection_id>/books/<int:book_id>/",
         views.CollectionBookDetailView.as_view(), name="collection-book-detail"),
    path("books/<int:book_id>/favourite", views.BookFavouriteView.as_view(),
         name="book-favourite"),

    path("continue-reading/", views.ContinueReadingView.as_view(), name="continue-reading"),

    path("upload/", views.UploadView.as_view(), name="upload"),
    path("uploads/", views.UploadBatchListView.as_view(), name="upload-batches"),
    path("uploads/<int:batch_id>/", views.UploadBatchDetailView.as_view(),
         name="upload-batch-detail"),

    path("trash/", views.TrashView.as_view(), name="trash"),
    path("storage/", views.StorageStatusView.as_view(), name="storage"),
]
