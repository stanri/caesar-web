import tempfile
import zipfile
import json
from collections import defaultdict
from io import BytesIO

from django.conf import settings
from django.db import transaction
from django import forms
from djangorestframework import status
from djangorestframework.views import View
from djangorestframework.mixins import RequestMixin, AuthMixin
from djangorestframework.permissions import IsAuthenticated, BasePermission
from djangorestframework.authentication import \
        BasicAuthentication, UserLoggedInAuthentication
from djangorestframework.response import ErrorResponse

from django.contrib.auth.models import User
from chunks.models import Assignment, Submission, File, Chunk
from review.models import Comment
from utils.decorators import memoized


_403_FORBIDDEN_RESPONSE = ErrorResponse(
    status.HTTP_403_FORBIDDEN,
    {'detail': 'You do not have permission to access this resource. ' +
               'You may need to login or otherwise authenticate the request.'})


class IsStaffUser(BasePermission):
    """
    Allows access only to admin users.
    """
    def check_permission(self, user):
        if not user.is_staff:
            raise _503_FORBIDDEN_RESPONSE

class BundleForm(forms.Form):
    bundle = forms.FileField()


class BundleView(View, RequestMixin, AuthMixin):
    permissions = (IsStaffUser,)
    authentication = (BasicAuthentication, UserLoggedInAuthentication)

    form = BundleForm

    def post(self, request):
        uploaded_bundle = self.FILES['bundle']
        if not hasattr(uploaded_bundle, 'temporary_file_path'):
            f = BytesIO(uploaded_bundle.read())
        else:
            tmp_file_path = uploaded_bundle.temporary_file_path
            f = open(tmp_file_path)
        bundle_zip = zipfile.ZipFile(file=f, mode='r')
        self._process_bundle_zip(bundle_zip)


    def _process_bundle_zip(self, bundle_zip):
        assignment_file = bundle_zip.read('assignment.json')
        chunks_file = bundle_zip.read('chunks.json')
        assignment_info = json.loads(assignment_file)
        chunks_info = json.loads(chunks_file)

        @memoized
        def get_user(username):
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist:
                return None

        file_map = {}
        with transaction.commit_on_success():
            assignment = Assignment(name=assignment_info['name'])
            assignment.save()
            for submission_info in assignment_info['submissions']:
                submission = Submission(
                        name=submission_info['name'],
                        assignment=assignment
                )
                submission.save()
                for file_info in submission_info['files']:
                    uuid = file_info['uuid']
                    with bundle_zip.open('files/' + uuid) as data:
                        sourceFile = File(
                                path=file_info['path'],
                                data=data.read(),
                                submission=submission
                        )
                        sourceFile.save()
                        file_map[uuid] = sourceFile

            for chunk_info in chunks_info:
                chunk = Chunk(
                        name=chunk_info['name'],
                        start=chunk_info['start'],
                        end=chunk_info['end'],
                        file=file_map[chunk_info['file_uuid']]
                )
                if 'cluster_id' in chunk_info:
                    chunk.cluster_id = chunk_info['cluster_id']
                chunk.save()
                for comment_info in chunk_info['comments']:
                    comment = Comment(
                            text=comment_info['text'],
                            start=comment_info['start'],
                            end=comment_info['end'],
                            type=comment_info['type'],
                            author=get_user(comment_info['author']),
                            chunk=chunk
                    )
                    comment.save()


