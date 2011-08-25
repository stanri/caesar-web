from djangorestframework.resources import ModelResource
from review.models import Comment
from chunks.models import Chunk

class CommentResource(ModelResource):
    model = Comment
    fields = ('text', 'author_id', 'start', 'end', 'type', 'chunk_id')


class ChunkResource(ModelResource):
    model = Chunk
