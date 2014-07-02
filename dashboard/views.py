from django.core import serializers
from django.db.models import Q, Count, Max
from django.shortcuts import render, redirect, get_object_or_404
from django.template import RequestContext
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, Http404
from django.core.urlresolvers import reverse
from  django.core.exceptions import ObjectDoesNotExist

from chunks.models import Chunk, Assignment, Milestone, SubmitMilestone, ReviewMilestone, Submission, StaffMarker
from review.models import Comment, Vote
from tasks.models import Task
from tasks.routing import assign_tasks
from accounts.models import UserProfile, Extension, Member
from notifications.models import Notification

import datetime
import sys
import operator
import logging

#METHODS FOR URLS
@login_required
def dashboard(request):
    user = request.user

    # assign new reviewing tasks to this user
    new_task_count = 0
    allow_requesting_more_tasks = False
    live_review_milestones = ReviewMilestone.objects.filter(assigned_date__lt=datetime.datetime.now(),\
         duedate__gt=datetime.datetime.now(), assignment__semester__members__user=user).all()
    for review_milestone in live_review_milestones:
        current_tasks = user.tasks.filter(milestone=review_milestone)
        active_sub = Submission.objects.filter(authors=user, milestone=review_milestone.submit_milestone)
        try:
            membership = Member.objects.get(user=user, semester=review_milestone.assignment.semester)
            if active_sub.count() or not Member.STUDENT in membership.role:
                #logging.debug("I can have assignments")
                # user is a student with an existing submission, or isn't a student
                # allow user to request more tasks manually
                allow_requesting_more_tasks = True
                if not current_tasks.count():
                    # automatically assign new tasks to student ONLY if they don't already have tasks
                    #logging.debug("assigning tasks")
                    new_task_count += assign_tasks(review_milestone, user)
        except ObjectDoesNotExist:
            pass

    return dashboard_for(request, user, new_task_count)

@login_required
def all_activity(request):
    user = request.user
    maxNotifications = 1000
    my_code_notifications_all = get_recent_notifications(user, maxNotifications)
    other_code_notifications_all = get_recent_notifications(user, maxNotifications)
    return render(request, 'dashboard/activity.html', {
        'my_code_notifications_all': my_code_notifications_all,
        'other_code_notifications_all': other_code_notifications_all
    })

@staff_member_required
def student_dashboard(request, username):
    try:
        other_user = User.objects.get(username=username)
    except:
        raise Http404
    return dashboard_for(request, other_user)


# HELPER METHODS FOR NOTIFICATIONS BELOW
#Note: The methods that use filter for notifications aren't used by what we wrote, but are left here
#in case someone needs them in the future for other updates to Caesar.
'''
Returns a list of tuples in the form of (i, i.created) where i is a notification that comes from a comment
on the Users code sample.
'''
def collect_comments_from_submissions(dashboard_user):
    all_notifications = []
    user_submission_notifications = Notification.objects.filter(recipient=dashboard_user).filter(reason='C')
    for notification in user_submission_notifications:  #this is done to have a list of notifications instead of a list of lists.
        all_notifications.append((notification, notification.created))
    return all_notifications

'''
Returns a list of tuples in the form of (reply, reply.created) where reply is a comment that is a child
to a parent comment created by the dashboard user.
'''
def collect_replies_to_user(dashboard_user):
    replies = []
    submission_notifications = Notification.objects.filter(recipient=dashboard_user).filter(reason='R').select_related('comment')
    for notification in submission_notifications:
        if notification.comment.parent is not None:
            if notification.comment.parent.author == dashboard_user:
                replies.append((notification, notification.created))
    return replies

'''
Returns a list of tuples in the form of (i, i.created) where i is a notification that comes from activity on
both the Users code and Others' code
'''
def collect_activity(dashboard_user):
    #TODO: how can i do this in one query?
    user_activity = Notification.objects.filter(recipient=dashboard_user).filter(reason='U')
    general_activity = Notification.objects.filter(recipient=dashboard_user).filter(reason='A')
    all_notifications = [(i, i.created) for i in user_activity]
    all_notifications.extend([(i, i.created) for i in general_activity])
    return all_notifications

'''
Returns a list of notifications in the form of (notification, notification.vote.modified) with the comment with the most recent
vote activity at the end of the list.
'''
def collect_recent_votes(dashboard_user):
    votes_tuple_list = []
    votes_on_user = Notification.objects.filter(recipient=dashboard_user).filter(reason='V')
    for vote_notification in votes_on_user:
        votes_tuple_list.append((vote_notification, vote_notification.vote.modified))
    return votes_tuple_list

'''
Returns a list of all notififcations for a user.
'''
def collect_all_notifications(dashboard_user):
    notifications_list = []
    all_notifications = Notification.objects.filter(recipient=dashboard_user).select_related('comment__chunk__file__submission__authors')
    for notification in all_notifications:
        if notification.vote is not None:
            notifications_list.append((notification, notification.vote.modified))
        else:
            notifications_list.append((notification, notification.created))
    return notifications_list

'''
Returns a sorted list all of the list arguments by their time of modification or creation, depending on the object,
where the 0 index is used for the latest action. (votes use modification time, comments use creation time)
@param *args - Any number of arguments passed in. Arguments should be a list of tuples in the form (notification,
notification.created).
'''
def create_recent_activity_list(*args):
    list_of_lists = [i for i in args]

    #list comp. flattens list_of_lists
    #(see http://stackoverflow.com/questions/716477/join-list-of-lists-in-python)
    recent_activity_tuple = [inner for outer in list_of_lists for inner in outer]

    #sorts the list by the time entry in the second position of each tuple.
    recent_activity_tuple.sort(key = lambda object_time_tuple: object_time_tuple[1])

    #Now that sorting is done, create a list of just the notification objects with snippets
    recent_activity = add_snippets([i[0] for i in recent_activity_tuple] )
    return recent_activity[::-1] #we reverse the list, because the list has 0 index as earliest action.

## End of unused methods
## 

'''
Returns a list of the five most recent and unseen notifications on the users' code and a list of the five most recent
and unseen notifications on others' code that the user is related to.
'''
def get_recent_notifications(dashboard_user, maxNotifications = 5):
    my_notifications = []
    other_notifications = []
    #using prefetch_related because submission can have MULTIPLE authors (many-to-one not supported by select_related)
    new_notifications = Notification.objects.filter(recipient=dashboard_user, seen=False).order_by('-created').prefetch_related('submission__authors')
    for notification in new_notifications:
        authors = notification.submission.authors.all()
        if len(my_notifications) < maxNotifications and dashboard_user in authors:
            my_notifications.append(notification)
        if len(other_notifications) < maxNotifications and dashboard_user not in authors:
            other_notifications.append(notification)
        if len(my_notifications) >= maxNotifications and len(other_notifications) >= maxNotifications:
            break
    return add_snippets(my_notifications), add_snippets(other_notifications)

'''
Turns a list of notifications into list of tuples (notification, snippet)
'''
def add_snippets(notifications):
    notifications_with_snippets = []
    snippet_max_len = 100
    for notif in notifications:
        snippet = "Snippet not found."
        if notif.comment is not None: #this should always happen, unless notification has no comment for whatever reason
            snippet = notif.comment.chunk.generate_snippet(notif.comment.start, notif.comment.end)
            if len(snippet) > snippet_max_len:
                snippet = snippet[:snippet_max_len]
        notifications_with_snippets.append( (notif,snippet) )
    return notifications_with_snippets



def dashboard_for(request, dashboard_user, new_task_count = 0, allow_requesting_more_tasks = False):
    def annotate_tasks_with_counts(tasks):
        return tasks.annotate(comment_count=Count('chunk__comments', distinct=True),
                       reviewer_count=Count('chunk__tasks', distinct=True))
        #logging.log(tasks.all()[0].comment_count)

    all_tasks = dashboard_user.tasks \
        .select_related('submission', 'chunk__file__submission__milestone', 'milestone__assignment__semester__subject')
    active_tasks = all_tasks \
        .exclude(status='C') \
        .exclude(status='U') \
        .order_by('chunk__name', 'submission__name')
    active_tasks = annotate_tasks_with_counts(active_tasks)

    old_completed_tasks = all_tasks \
        .filter(status='C') \
        .exclude(chunk__file__submission__milestone__assignment__semester__is_current_semester=True)
    old_completed_tasks = annotate_tasks_with_counts(old_completed_tasks)

    completed_tasks = all_tasks \
        .filter(status='C') \
        .filter(chunk__file__submission__milestone__assignment__semester__is_current_semester=True) \
        .order_by('completed').reverse()
    completed_tasks = annotate_tasks_with_counts(completed_tasks)

    #get all the submissions that the user submitted
    submissions = Submission.objects.filter(authors=dashboard_user) \
        .filter(milestone__duedate__lt=datetime.datetime.now()) \
        .order_by('milestone__duedate')\
        .filter(milestone__assignment__semester__is_current_semester=True)\
        .select_related('chunk__file__assignment') \
        .annotate(last_modified=Max('files__chunks__comments__modified'))\
        .reverse()

    '''
    Gathers data from submissions of a user, including comments and number of reviewers on those submissions.
    @attr - submissions - QuerySet of submissions.
    '''
    def collect_submission_data(submissions):
        data = []
        for submission in submissions:
            user_comments = Comment.objects.filter(chunk__file__submission=submission).filter(type='U').count()
            static_comments = Comment.objects.filter(chunk__file__submission=submission).filter(type='S').count()
            reviewer_count = User.objects.filter(tasks__chunk__file__submission = submission).count()
            data.append((submission, reviewer_count, submission.last_modified,
                                      user_comments, static_comments))
        return data

    submission_data = collect_submission_data(submissions)
    my_code_notifications, other_code_notifications = get_recent_notifications(dashboard_user)
    recent_activity_objects = create_recent_activity_list(collect_all_notifications(dashboard_user))

    #get all the submissions that the user submitted, in previous semesters
    old_submissions = Submission.objects.filter(authors=dashboard_user) \
        .filter(milestone__duedate__lt=datetime.datetime.now()) \
        .order_by('milestone__duedate')\
        .exclude(milestone__assignment__semester__is_current_semester=True)\
        .select_related('chunk__file__assignment') \
        .annotate(last_modified=Max('files__chunks__comments__modified'))\
        .reverse()

    old_submission_data = collect_submission_data(old_submissions)

    #find the current submissions
    current_milestones = SubmitMilestone.objects.filter(assignment__semester__members__user=dashboard_user, assignment__semester__members__role=Member.STUDENT)\
        .filter(assigned_date__lt= datetime.datetime.now())\
        .order_by('duedate')

    current_milestone_data = []
    for milestone in current_milestones:
        try:
            user_extension = milestone.extensions.get(user=dashboard_user)
            extension_days = user_extension.slack_used
        except ObjectDoesNotExist:
            user_extension = None
            extension_days = 0
        if datetime.datetime.now() <= milestone.duedate + datetime.timedelta(days=extension_days) + datetime.timedelta(hours=2):
            current_milestone_data.append((milestone, user_extension))

    #find total slack days left for each membership
    current_memberships = Member.objects.filter(user=dashboard_user)

    current_slack_data = []
    for membership in current_memberships:
            total_slack = membership.slack_budget
            used_slack = sum([extension.slack_used for extension in Extension.objects.filter(user=dashboard_user, milestone__assignment__semester=membership.semester)])
            slack_left = total_slack - used_slack
            current_slack_data.append((membership.semester, slack_left))

    return render(request, 'dashboard/dashboard.html', {
        'active_tasks': active_tasks,
        'completed_tasks': completed_tasks,
        'old_completed_tasks': old_completed_tasks,
        'new_task_count': new_task_count,
        'submission_data': submission_data,
        'old_submission_data': old_submission_data,
        'current_milestone_data': current_milestone_data,
        'allow_requesting_more_tasks': allow_requesting_more_tasks,
        'recent_activity_objects': recent_activity_objects,
        'current_slack_data': current_slack_data,
        'my_code_notifications': my_code_notifications,
        'other_code_notifications': other_code_notifications,
    })




