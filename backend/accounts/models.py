"""The canonical application identity.

PRD principle 1: the Django user is the identity. A Google account is an
optional *link* on top of this model, never a prerequisite for having one.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("An email address is required.")
        # normalize_email only lowercases the domain. Lowercasing the whole
        # address prevents Alice@x.com and alice@x.com becoming two accounts,
        # which would also make Google account linking ambiguous.
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("role", User.Role.USER)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("role", User.Role.ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("A superuser must have is_staff and is_superuser set.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        USER = "user", "User"
        ADMIN = "admin", "Admin"

    email = models.EmailField(unique=True)  # unique implies an index in Postgres
    display_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.USER)

    # Django plumbing. `is_active=False` is the disable-account switch (PRD §8):
    # it blocks login everywhere without deleting the user's library or notes.
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False,
        help_text="Grants access to Django Admin.",
    )

    # How much of the library disk this account may fill, in bytes. Blank means
    # "whatever the instance default is", so raising the default lifts everyone
    # who has not been given a specific allowance; 0 means no limit at all.
    # Two sentinels rather than one because "unlimited" and "unset" are
    # genuinely different answers, and collapsing them would make an explicit
    # exemption silently revert the next time the default changed.
    storage_quota_bytes = models.BigIntegerField(
        null=True, blank=True,
        help_text="Bytes this account may store. Blank uses the instance "
                  "default; 0 means unlimited.",
    )

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["email"]
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        return super().save(*args, **kwargs)

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN


# Imported here so `accounts.models.UserSettings` resolves and migrations pick
# it up; it lives in its own module to keep the identity model uncluttered.
from .settings_models import UserSettings  # noqa: E402,F401
