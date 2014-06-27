from django.template import Context, Template
from django.template.loader import get_template
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.sites.models import Site
from django.contrib.auth.models import User
from django.contrib.contenttypes import generic
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from email_templates import send_templated_mail

from review.models import Comment, Vote
from chunks.models import Submission
import datetime
import sys


class Notification(models.Model):
    SUMMARY = 'S'
    RECEIVED_REPLY = 'R'
    COMMENT_ON_SUBMISSION = 'C'
    VOTE_ON_COMMENT = 'V'
    ACTIVITY_ON_CHUNK = 'A'
    REASON_CHOICES = (
            (SUMMARY, 'Summary'),
            (RECEIVED_REPLY, 'Received reply'),
            (COMMENT_ON_SUBMISSION, 'Received comment on submission'),
    )

    submission = models.ForeignKey(Submission, blank=True, null=True, related_name='notifications')
    comment = models.ForeignKey(Comment, blank=True, null=True, related_name='notifications')
#    vote = models.ForeignKey(Vote, blank=True, null=True, related_name='notifications')
#   sender = models.ForeignKey(User, related_name='notifications')
    recipient = models.ForeignKey(User, related_name='notifications')
    reason = models.CharField(max_length=1, blank=True, choices=REASON_CHOICES)
    created = models.DateTimeField(auto_now_add=True)
    email_sent = models.BooleanField(default=False)
    seen = models.BooleanField(default=False)

    class Meta:
        ordering = [ '-created' ]


NEW_SUBMISSION_COMMENT_SUBJECT_TEMPLATE = Template(
        "[{{ site.name }}] {{ comment.author.get_full_name|default:comment.author.username }} commented on your code")

NEW_REPLY_SUBJECT_TEMPLATE = Template(
        "[{{ site.name }}] {{ comment.author.get_full_name|default:comment.author.username }} replied to your comment")

# How these notifications work, with simple pseudocode:
# let's say sub = Submission(author = 'maxg')
# 'pnomario' comments on sub
# 'sarivera' comments on sub
# 'peipeipei' replies to 'pnomario'
#
# in this scenario, the following notifications would be created:
# 'maxg' gets a notification from 'pnomario', with reason 'C' (comment on submission)
# 'maxg' gets a notification from 'peipeipei', with reason 'A' (activity on chunk)
# 'maxg' gets a notification from 'sarivera', with reason 'C' (comment on submission)
#
# 'pnomario' gets a notification from 'peipeipei', with reason 'R' (reply on comment)
# 'pnomario' gets a notification from 'sarivera', with reason 'A' (comment on submission)
#
# 'sarivera' gets a notification from 'pnomario', with reason 'A' (comment on submission)
# 'sarivera' gets a notification from 'peipeipei', with reason 'A' (comment on submission)
#
# 'peipeipei' gets a notification from 'sarivera', with reason 'A' (comment on submission)
#
# nested replies should send a notification with reason 'R' all the way up the reply tree.

@receiver(post_save, sender=Vote)
def add_vote_notification(sender, instance, created=False, raw=False, **kwargs):
    if created and not raw:
        site = Site.objects.get_current()
        context = Context({
            'site': site,
            'vote': instance,
            'comment_author': instance.comment.author
        })
        notification = Notification(recipient = instance.comment.author, reason='V')
        notification.submission = instance.comment.chunk.file.submission
        notification.comment = instance.comment
        notification.save();
        return

'''
Creates a new Notification object for replies and new comments on a users
submission.
'''
#Note: comment in the args and in the 'comment': comment line might need to be instance
#i.e. ...(sender, instance...) and 'comment': instance
@receiver(post_save, sender=Comment)
def add_comment_notification(sender, comment, created=False, raw=False, **kwargs):
    if created and not raw:
        notified_users = set()
        site = Site.objects.get_current()
        context = Context({
                'site': site,
                'comment': comment,
                'chunk': comment.chunk,
                'submission': comment.chunk.file.submission
                'submission_author': comment.chunk.file.submission.authors.all() #this is a list of User objects!
            })

        #if the comment has a reply and the reply is not from the person who made the comment.
        #create a second variable to crawl up the reply tree for correct notification alerts.
        reply = comment
        while reply.parent is not None:
            if ((reply.parent.author != reply.author)):
                notification = Notification(recipient = comment.parent.author, reason='R')
                notification.submission = submission
                notification.comment = comment
                notification.save()
                reply = reply.parent #this is used to go up the reply tree.




        #otherwise, if the comment is a new comment on one of the users submissions.
        for i in



#Note: This method was used to send emails when people got a reply to a comment
#they made, but the email functionality was scrapped and the code basically created
#notifications when there was a reply, and only if the user had an email listed on
#caesar. I have rewritten this method, sans email functionality, in the methods above,
#but I leave this for future devs who may wish to implement emailing about replies.
#
#@receiver(post_save, sender=Comment)
#def send_comment_notification(sender, instance, created=False, raw=False, **kwargs):
#    if created and not raw:
#        site = Site.objects.get_current()
#        context = Context({
#            'site': site,
#            'comment': instance,
#            'chunk': instance.chunk
#        })
#        #comment gets a reply, the reply is not by the original author
#        if instance.parent and instance.parent.author.email \
#                and instance.parent.author != instance.author:
#            to = instance.parent.author.email
#            subject = NEW_REPLY_SUBJECT_TEMPLATE.render(context)
#            notification = Notification(recipient = instance.parent.author, reason='R')
#            notification.submission = instance.chunk.file.submission
#            notification.comment = instance
#            notification.save()
#
#            #sent = send_templated_mail(
#            #    subject, None, (to,), 'new_reply',
#            #    context, template_prefix='notifications/')
#            #notification.email_sent = sent
#            #notification.save()
#            return
#
#        return # NOTE(TFK): The code below is broken since submissions can have multiple authors.
#        submission_author = instance.chunk.file.submission.author
#        submission = instance.chunk.file.submission
#        #comment gets made on a submission after code review deadline has passed
#        if submission_author and submission_author.email \
#                and instance.author != submission_author\
#                and instance.author.username != "checkstyle" \
#                and datetime.datetime.now() > submission.code_review_end_date():
#            to = submission_author.email
#            subject = NEW_SUBMISSION_COMMENT_SUBJECT_TEMPLATE.render(context)
#            notification = Notification(recipient = submission_author, reason='C')
#            notification.submission = instance.chunk.file.submission
#            notification.comment = instance
#            notification.save()
#
#            #sent = send_templated_mail(
#             #       subject, None, (to,), 'new_submission_comment',
#              #      context, template_prefix='notifications/')
#           # notification.email_sent = sent
#            #notification.save()
#    pass

