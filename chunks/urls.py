from django.conf.urls.defaults import *

urlpatterns = patterns('chunks.views',
    (r'^view/(?P<chunk_id>\d+)', 'view_chunk'),
    (r'^submission/(?P<viewtype>(all|code))/(?P<submission_id>\d+)', 'view_all_chunks'),
    (r'^submit_assignment/(?P<assignment>\d+)', 'submit_assignment'),
)
