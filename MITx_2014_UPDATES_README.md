##MITx_2014_UPDATES_README

A group of 6.MITx UROP students worked on Caesar over the summer and added a few updates to Caesar.

Students now have the ability to upload personal code that can be viewed in their submitted code table on 
their dashboard. In order to do this, we created methods that work with the following databases:

a = Subject(name='Life')
b = Semester(semester='Lifetime', is_current_semester=True, subject=a) (should be marked as ongoing.)
c = Assignment(name='Personal Code Upload', semester=b)

These databases need to be created manually on the admin page or through the terminal for personal code upload to work. Keep in mind that all students have access to all private submissions, so students could potentially see others personal code by visiting url's with different submission id's.

There is now a way for students to see notifications on their dashboards. To do this, we added a seen category to the notifications model, allowing us to differentiate between what the user has been notified of and what they haven't seen, and we added methods to the views for data collection. This is used extensively in the activity.html page, which shows users all notifications they have received. 

Minor fixes also made include:
comments allow new lines.
teachers, students, and volunteers are now distinguished between in the comment ui.
the toolbar scrolls with the user on the chunks/view page.
