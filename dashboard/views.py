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


@login_required
def notificationSeen(request):
    if request.method == "POST":
        noteID = request.POST["notification_id"]
        note = Notification.objects.get(id=noteID)
        if note.recipient == request.user:
            note.seen = True
            note.save()


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
    maxNotifications = 1000 #should be more than enough to get all the
    my_code_notifications_all, other_code_notifications_all = get_recent_notifications(user, maxNotifications, False)
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

def get_recent_notifications(dashboard_user, maxNotifications = 5, filter_for_unseen = True):
    '''
    Returns most recent unseen notifications on the users' code and others' code related to the user.
    Returns TWO lists of tuples (notification, code snippet)
    dashboard_user - the user we're seeing the dashboard of, NOT the logged in user
    maxNotifications - the maximum number of notifications in each generated list
    filter_for_unseen - if True, we look for notifications that have not been marked as seen yet. If False, we get all notifications for the dashboard_user, regardless of their seen property.
    '''
    my_notifications = []
    other_notifications = []
    if filter_for_unseen:
        #using prefetch_related because submission can have MULTIPLE authors (many-to-one not supported by select_related)
        new_notifications = Notification.objects.filter(recipient=dashboard_user, seen=False).order_by('-created').prefetch_related('submission__authors')
    else:
        new_notifications = Notification.objects.filter(recipient=dashboard_user).order_by('-created').prefetch_related('submission__authors')
    for notification in new_notifications:
        authors = notification.submission.authors.all()
        if len(my_notifications) < maxNotifications and dashboard_user in authors:
            my_notifications.append(notification)
        if len(other_notifications) < maxNotifications and dashboard_user not in authors:
            other_notifications.append(notification)
        if len(my_notifications) >= maxNotifications and len(other_notifications) >= maxNotifications:
            break
    return add_snippets(my_notifications), add_snippets(other_notifications)


def add_snippets(notifications):
    '''
    Turns a list of notifications into list of tuples in the form (notification, snippet).
    '''
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
    '''
    Generates the dashboard for a specific user, which is passed in as the dashboard_user argument. This
    is particularly useful for staff to view students code.
    '''
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

    def collect_submission_data(submissions):
        '''
        Gathers data from submissions of a user, including comments and number of reviewers on those submissions.
        @attr - submissions - QuerySet of submissions.
        '''
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
        'current_slack_data': current_slack_data,
        'my_code_notifications': my_code_notifications,
        'other_code_notifications': other_code_notifications,
    })

