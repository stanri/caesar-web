from django.conf.urls.defaults import *

from djangorestframework.views import ListOrCreateModelView, InstanceModelView
from djangorestframework.mixins import AuthMixin
from djangorestframework.permissions import IsAuthenticated
from djangorestframework.authentication import \
        BasicAuthentication, UserLoggedInAuthentication

from .resources import CommentResource, ChunkResource
from .views import BundleView

class AuthenticatedListOrCreateView(ListOrCreateModelView, AuthMixin):
    permissions = (IsAuthenticated,)
    authentication = (BasicAuthentication, UserLoggedInAuthentication)

class AuthenticatedInstanceModelView(InstanceModelView, AuthMixin):
    permissions = (IsAuthenticated,)
    authentication = (BasicAuthentication, UserLoggedInAuthentication)

urlpatterns = patterns('',
   (r'^bundle/$', BundleView.as_view()),
   (r'^comments/$', 
       AuthenticatedListOrCreateView.as_view(resource=CommentResource)),
   (r'^comments/(?P<pk>\d+)/$',
       AuthenticatedInstanceModelView.as_view(resource=CommentResource)),
   (r'^chunks/(?P<pk>\d+)/$',
       AuthenticatedInstanceModelView.as_view(resource=ChunkResource)),
)
