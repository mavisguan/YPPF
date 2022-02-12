from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Position,
    OrganizationType,
    Position,
    Activity,
    ActivityPhoto,
    Participant,
    Reimbursement,
    Course,
    CourseTime,
    CourseParticipant,
    CourseRecord,
)
from app.course_utils import (
    create_course,
)
from app.comment_utils import addComment, showComment
from app.utils import (
    get_person_or_org,
    escape_for_templates,
)

import io
import csv
import os
import qrcode

import urllib.parse
from datetime import datetime, timedelta
from django.db import transaction
from django.db.models import Q, F



