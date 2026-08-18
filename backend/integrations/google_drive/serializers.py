from __future__ import annotations

from rest_framework import serializers

from .models import DriveConnection, DriveRoot, SyncRun


class DriveRootSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriveRoot
        fields = ("id", "provider_folder_id", "name", "original_path",
                  "sync_enabled", "last_synced_at")
        read_only_fields = ("id", "last_synced_at")


class SyncRunSerializer(serializers.ModelSerializer):
    counts = serializers.DictField(read_only=True)

    class Meta:
        model = SyncRun
        fields = ("id", "status", "started_at", "finished_at", "counts", "error_summary")
        read_only_fields = fields


class DriveConnectionSerializer(serializers.ModelSerializer):
    roots = DriveRootSerializer(many=True, read_only=True)
    needs_reauthorization = serializers.BooleanField(read_only=True)
    latest_sync = serializers.SerializerMethodField()

    class Meta:
        model = DriveConnection
        # refresh_token is absent by construction rather than excluded, so a
        # future field addition cannot accidentally expose it (PRD §9).
        fields = ("id", "provider_email", "status", "status_detail",
                  "needs_reauthorization", "last_synced_at", "sync_requested_at",
                  "created_at", "roots", "latest_sync")
        read_only_fields = fields

    def get_latest_sync(self, obj):
        run = obj.sync_runs.first()
        return SyncRunSerializer(run).data if run else None


class DriveFolderSerializer(serializers.Serializer):
    """A folder in the picker. Not a model — this is live Drive data."""

    id = serializers.CharField()
    name = serializers.CharField()
    path = serializers.CharField(required=False, allow_blank=True)


class AddRootSerializer(serializers.Serializer):
    provider_folder_id = serializers.CharField(max_length=255)
    name = serializers.CharField(max_length=512)
    original_path = serializers.CharField(max_length=2048, required=False, allow_blank=True)


class DisconnectSerializer(serializers.Serializer):
    # PRD §33: disconnecting must not destroy the library unless explicitly
    # asked. Defaults to keeping everything.
    delete_library = serializers.BooleanField(default=False)
