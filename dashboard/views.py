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
from review.models import Comment
from tasks.models import Task
from tasks.routing import assign_tasks
from accounts.models import UserProfile, Extension, Member

import datetime
import sys
import logging

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

@staff_member_required
def student_dashboard(request, username):
    try:
        other_user = User.objects.get(username=username)
    except:
        raise Http404
    return dashboard_for(request, other_user)

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

    '''
    Gathers data from submissions of a user, including comments and number of reviewers on those submissions.
    @attr - submissions - QuerySet of submissions by the user.
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

    '''
    Returns a list of user-generated comments (NOT A LIST OF LISTS) for all submissions of a user,
    sorted by their date of creation. The first entry in the list is the earliest comment, and the last
    entry is the latest comment.
    @param - submissions - QuerySet of submissions by the user.
    '''
    def collect_comments_from_submissions(submissions):
        all_comments = []
        for submission in submissions:
            user_code_comments = Comment.objects.filter(chunk__file__submission=submission).filter(type='U')
            for comment in user_code_comments:  #this is done to have a list of comments instead of a list of lists.
                all_comments.append(comment)
        all_comments.sort(key = lambda comment: comment.created) #all_comments[0] is the earliest comment, last index is latest.
        return all_comments

    '''
    Returns a list of replies to the users comments, which are themselves comments.
    @param - submissions - QuerySet of submissions by the user.
    '''
    #TODO: this need to be run on a set of submissions where the user is a comment author.
    def collect_replies_to_user(submissions):
        replies = []
        for submission in submissions:
            user_code_comments = Comment.objects.filter(chunk__file__submission=submission).filter(type='U')
            for comment in user_code_comments:
                if comment.parent.author == dashboard_user:
                    replies.append(reply)
        replies.sort(key = lambda reply: reply.created)
        return replies

    '''
    Returns a list of comments with recent vote activity, with the comment with the most recent
    vote activity at the end of the list.
    @param - submisssions - QuerySet of submissions by the user.
    '''
    def collect_recently_voted_comments(submissions):
        all_votes = []
        comments = []
        for submission in submissions:
            submission_votes = Votes.objects.filter(comment.author==dashboard.user)
            for vote in submission_votes:
                all_votes.append(vote)
        all_votes.sort(key = lambda vote: vote.modified)
        for vote in all_votes:
            comments.append(vote.comment)
        #ISSUE: vote.modified time is lost by doing this...
        #IDEA: store things in all 3 methods in form of (vote or comment, time) tuples,
        #and sort by the time in the tuple, then return the sorted list of just the
        #first elements in the sort_recent_activity_list method below.
        return comments

    '''
    Sorts all of the list arguments by their time of modification, where the 0 index is used for the earliest
    action.
    @param comments_list - list generated from collect_comments_from_submissions
    @param replies_list - list generated from collect_replies_to_user
    @param comments_from_vote_list - list generated from collect_recently_voted_comments
    '''
    def sort_recent_activity_list(comments_list, replies_list, comments_from_vote_list):
        list_of_lists = [comments_list, replies_list, comments_from_vote_list]

        #list comp. flattens list_of_lists
        #(see http://stackoverflow.com/questions/716477/join-list-of-lists-in-python)
        recent_activity = [inner for outer in list_of_lists for inner in outer]
        #TODO: problem with sort: can i sort by type? I need to use modified for vote and
        #created for reply and submission.
#        recent_activity.sort(key = lambda x: x.created)



    #get all the submissions that the user submitted
    submissions = Submission.objects.filter(authors=dashboard_user) \
        .filter(milestone__duedate__lt=datetime.datetime.now()) \
        .order_by('milestone__duedate')\
        .filter(milestone__assignment__semester__is_current_semester=True)\
        .select_related('chunk__file__assignment') \
        .annotate(last_modified=Max('files__chunks__comments__modified'))\
        .reverse()

    all_submissions = Submission.objects.all()

    submission_data = collect_submission_data(submissions)
    #TODO: make sure this isn't too time intensive.
    submission_comments = collect_comments_from_submissions(submissions) #TODO: maybe expand this into old_submission_data too
    submission_replies = collect_replies_to_user(all_submissions)
    submission_voted_recently = collect_recently_voted_comments(all_submissions)

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

    return render(request, 'dashboard/dashboard.html', {
        'active_tasks': active_tasks,
        'completed_tasks': completed_tasks,
        'old_completed_tasks': old_completed_tasks,
        'new_task_count': new_task_count,
        'submission_data': submission_data,
        'old_submission_data': old_submission_data,
        'current_milestone_data': current_milestone_data,
        'allow_requesting_more_tasks': allow_requesting_more_tasks,
        'submission_comments': submission_comments,
    })


