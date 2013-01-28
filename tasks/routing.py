from __future__ import division

from collections import namedtuple, defaultdict
import itertools

from django.db.models import Count
from django.contrib import auth
from django.contrib.auth.models import User as User_django

from chunks import models
from models import Task
import random
import sys
import app_settings

__all__ = ['assign_tasks']

# WARNING: These classes shadow the names of the actual model objects
# that they represent. This is deliberate. I am sorry.
class User:
    def __init__(self, id, role, reputation):
        self.id = id
        self.role = role
        self.reputation = reputation
        self.submissions = []
        self.chunks = []
        self.other_reviewers = set()
        self.clusters = defaultdict(lambda : 0)

    def __unicode__(self):
        return u"User(id=%d, role=%s, reputation=%d)" % \
                (self.id, self.role, self.reputation)

    def __str__(self):
        return unicode(self).encode('utf-8')

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return self.id

class Submission:
    def __init__(self, id, author, chunks):
        self.id = id
        self.author = author
        self.reviewers = set()
        self.chunks = [Chunk(chunk=chunk, submission=self)
                for chunk in chunks]

    def __str__(self):
        return unicode(self).encode('utf-8')

class Chunk:
    def __init__(self, chunk, submission):
        self.id = chunk['id']
        self.name = chunk['name']
        self.cluster_id = chunk['cluster_id']
        self.submission = submission
        self.reviewers = set()
        self.class_type = chunk['class_type']
        self.student_lines = chunk['student_lines']
        self.return_count = 0
        self.for_nesting_depth = 0
        self.if_nesting_depth = 0

    def assign_reviewer(self, user):
        if user in self.reviewers:
            return False

        self.reviewers.add(user)
        self.submission.reviewers.add(user)

        user.chunks.append(self)
        user.other_reviewers.update(self.reviewers)
        if self.cluster_id:
            user.clusters[self.cluster_id] += 1

        for reviewer in self.reviewers:
            reviewer.other_reviewers.add(user)
        return True

def _convert_role(role):
    return {'T': 'staff', 'S': 'student'}.get(role, 'other')
def _convert_role_to_count(assignment, role):
    return {'staff': assignment.staff_count, 'student': assignment.student_count, 'other':assignment.alum_count}.get(role)

def _convert_assignment_to_priority(assignment):
    to_assign = assignment.chunks_to_assign
    priority_dict = dict()
    for chunk_info in to_assign.split(",")[0:-1]:
        split_info = chunk_info.split(" ")
        if int(split_info[1]):
            priority_dict[split_info[0]] = -1
        else:
            priority_dict[split_info[0]] = 0

    return priority_dict

def load_users():
    # load all existing users
    user_map = defaultdict(lambda : None)
    django_users = auth.models.User.objects.select_related('profile').all()
    for u in django_users:
        user_map[u.id] = User(
                id=u.id,
                role=_convert_role(u.profile.role),
                reputation=u.profile.reputation)
    return user_map


def load_chunks(assignment, user_map, django_user):
    chunks = []
    chunk_map = {}
    submissions = {}

    django_submissions = assignment.submissions.exclude(author=django_user).values()
    django_chunks = models.Chunk.objects \
            .filter(file__submission__assignment=assignment) \
            .exclude(file__submission__author=django_user) \
            .values('id', 'name', 'cluster_id', 'file__submission', 'class_type', 'student_lines')
    django_tasks = Task.objects.filter(
            chunk__file__submission__assignment=assignment) \
            .exclude(chunk__file__submission__author=django_user) \
                    .select_related('reviewer__user') \

    # load all submissions and chunks into lightweight internal objects
    django_submission_chunks = defaultdict(list)
    for chunk in django_chunks:
        django_submission_chunks[chunk['file__submission']].append(chunk)

    for django_submission in django_submissions:
        submission = Submission(
                id=django_submission['id'],
                author=user_map[django_submission['author_id']],
                chunks=django_submission_chunks[django_submission['id']])
        if not submission.chunks:
            # toss out any submissions without chunks
            continue
        submissions[submission.id] = submission
        chunks.extend(submission.chunks)


    # load existing reviewing assignments
    for chunk in chunks:
        chunk_map[chunk.id] = chunk

    for django_task in django_tasks:
        chunk = chunk_map[django_task.chunk_id]
        reviewer = user_map[django_task.reviewer.user_id]
        chunk_map[django_task.chunk_id].assign_reviewer(reviewer)

    return chunks


def find_chunks(user, chunks, count, reviewers_per_chunk, min_student_lines, priority_dict):
    """
    Computes the IDs of the chunks for this user to review on this assignment.

    Does not assign them, this method simply retrieves chunk instances and
    returns a generator of them.
    """

    # TODO(mglidden): update this comment
    # Sort the chunks according to these criteria:
    #
    # For students and other:
    #  1. Remove chunks already assigned to the user
    #  2. Remove chunks with maximum number of reviewers
    #  3. Find chunks with largest number of reviewers
    #  4. Sort those chunks by number of reviewers assigned to submission,
    #     which tries to distribute reviewers fairly among submissions.
    #  5. Maximize affinity between user and reviewers on the submission,
    #     which increases diversity of reviewers for submitter.
    #  6. Maximize affinity between user and reviewers on the chunk, which
    #     increases diversity of other reviewers for reviewer.
    #
    # For staff, we simply try to spread them out to maximize number of
    # submissions with at least one staff member, and then maximize the number
    # of students that get to review a chunk along with staff.

    def compute_affinity(user1, user2):
        distance_affinity = 0
        if user2 in user1.other_reviewers:
            distance_affinity -= 50

        reputation_affinity = abs(user1.reputation - user2.reputation)

        role_affinity = 0
        role1, role2 = user1.role, user2.role
        if role1 == 'student' and role2 == 'staff' or \
                role1 == 'staff' and role2 == 'student':
            role_affinity = 2
        elif role1 == 'staff' and role2 == 'staff':
            role_affinity = -100
        else:
            role_affinity = (role1 != role2)
        role_affinity *= app_settings.ROLE_AFFINITY_MULTIPLIER

        return distance_affinity + reputation_affinity + role_affinity

    def total_affinity(user, reviewers):
        affinity = 0
        for reviewer in reviewers:
            affinity += compute_affinity(user, reviewer)
        return affinity

    def is_not_chunk_author(chunk):
      return user is not chunk.submission.author

    def is_not_already_reviewing(chunk):
      return user not in chunk.reviewers

    def has_enough_lines(chunk):
      return True # preprocessor doesn't support student lines yet
      return chunk.student_lines > min_student_lines

    def number_of_reviewers(chunk):
      if len(chunk.reviewers) >= reviewers_per_chunk:
        return 0
      return (len(chunk.reviewers) + 1.0) / (reviewers_per_chunk + 1.0) # the +1s mean that a chunk without any reviewers will be reviewed before a chunk with n reviewers.

    def rand(chunk):
      return random.random() / reviewers_per_chunk

    hard_rules = [is_not_chunk_author, is_not_already_reviewing, has_enough_lines] # A chunk __must__ pass all hard rules to be given reviews. All items should be functions that return a boolen if the chunk could be assigned to the current user. The functions should take a single parameter - chunk
    soft_rules = [number_of_reviewers, rand] # Soft rules influence the order that chunks get reviewed it. Each item should return a value between 0 and 1. The chunk with the highest score gets reviewed first.


    def and_hard_rules(chunk):
      for rule in hard_rules:
        if not rule(chunk):
          return False
      return True

    def sum_soft_rules(chunk):
      return sum([rule(chunk) for rule in soft_rules])

    filtered = filter(and_hard_rules, chunks)
    return [chunk.id for chunk in sorted(filtered, key=sum_soft_rules)[:count]]

def _generate_tasks(assignment, reviewer, chunk_map,  chunk_id_task_map=defaultdict(list), max_tasks=sys.maxint, assign_more=False):
    """
    Returns a list of tasks that should be assigned to the given reviewer.
    assignment: assignment that tasks should be generated for
    reviewer: user object to create more tasks for
    chunk_map: map of chunk ids to chunk object returned by load_chunks. If simulating routing, use the same chunk_map object each time.
    chunk_id_task_map: map of chunk ids to lists of the assigned tasks. If simulating routing, use the same chunk_id_task_map each time.
    """

    #unfinished_task_count = Task.objects.filter(reviewer=reviewer.id, chunk__file__submission__assignment=assignment).exclude(status='C').count()
    unfinished_tasks = Task.objects.filter(reviewer=reviewer.id, chunk__file__submission__assignment=assignment)
    if assign_more:
      unfinished_tasks = unfinished_tasks.exclude(status='C').exclude(status='U')

    unfinished_task_count = unfinished_tasks.count()

    num_tasks_to_assign = assignment.num_tasks_for_user(reviewer) - unfinished_task_count
    if num_tasks_to_assign <= 0:
      return []

    if unfinished_task_count > 0:
      return []

    num_tasks_to_assign = min(num_tasks_to_assign, max_tasks)

    chunk_type_priorities = _convert_assignment_to_priority(assignment)

    tasks = []
    for chunk_id in find_chunks(reviewer, chunk_map.values(), num_tasks_to_assign, assignment.reviewers_per_chunk, assignment.min_student_lines, chunk_type_priorities):
      task = Task(reviewer_id=User_django.objects.get(id=reviewer.id).profile.id, chunk_id=chunk_id)

      chunk_id_task_map[chunk_id].append(task)
      chunk_map[chunk_id].reviewers.add(reviewer)
      chunk_map[chunk_id].submission.reviewers.add(reviewer)
      tasks.append(task)

    return tasks

def assign_tasks(assignment, reviewer, max_tasks=sys.maxint, assign_more=False):
  user_map = load_users()
  chunks = load_chunks(assignment, user_map, reviewer)
  chunk_map = {}
  for chunk in chunks:
    chunk_map[chunk.id] = chunk

  tasks = _generate_tasks(assignment, user_map[reviewer.id], chunk_map, max_tasks=max_tasks, assign_more=assign_more)

  [task.save() for task in tasks]

  return len(tasks)

def simulate_tasks(assignment, num_students, num_staff, num_alum):
  user_map = load_users()
  chunks = load_chunks(assignment, user_map, None)
  chunk_map = {}
  for chunk in chunks:
    chunk_map[chunk.id] = chunk
  chunk_id_task_map = defaultdict(list)

  #for i in range(0, num_students + num_staff + num_alum):
  #  if i < num_students:
  #    reviewer =
  #  elif i < num_students + num_staff:
  #    reviewer =
  #  else:
  #    reviewer =
  for reviewer in user_map.values():
    _generate_tasks(assignment, user_map[reviewer.id], chunk_map, chunk_id_task_map=chunk_id_task_map)

  return chunk_id_task_map
