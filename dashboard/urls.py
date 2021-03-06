from django.conf.urls.defaults import *

urlpatterns = patterns('dashboard.views',
    (r'^$', 'dashboard'),
    (r'^dashboard/(?P<username>\w+)', 'student_dashboard'),
    (r'^activity$', 'all_activity'),
    (r'^notificationSeen/$', 'notificationSeen'),
    (r'^code_upload$', 'code_upload'),
    (r'^submit_code_upload$', 'submit_code_upload'),
)

