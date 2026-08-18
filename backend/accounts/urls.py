from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("csrf/", views.CsrfView.as_view(), name="csrf"),
    path("session/", views.SessionView.as_view(), name="session"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password-change"),
    path("password/reset/", views.PasswordResetRequestView.as_view(), name="password-reset"),
    path("password/reset/confirm/", views.PasswordResetConfirmView.as_view(),
         name="password-reset-confirm"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("settings/", views.UserSettingsView.as_view(), name="settings"),
    path("account/delete/", views.AccountDeleteView.as_view(), name="account-delete"),
]
