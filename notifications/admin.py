from django.contrib import admin

from notifications.models import Notification

class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'created', 'reason', 'comment', 'submission', 'email_sent', 'seen')
    search_fields = ('comment', 'submission', 'recipient')


admin.site.register(Notification, NotificationAdmin)
