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
    path("continue-reading/", views.ContinueReadingView.as_view(), name="continue-reading"),

    path("upload/", views.UploadView.as_view(), name="upload"),
    path("uploads/", views.UploadBatchListView.as_view(), name="upload-batches"),
    path("uploads/<int:batch_id>/", views.UploadBatchDetailView.as_view(),
         name="upload-batch-detail"),

    path("trash/", views.TrashView.as_view(), name="trash"),
    path("storage/", views.StorageStatusView.as_view(), name="storage"),
]
