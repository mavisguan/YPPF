from calendar import c
from app.utils_dependency import *
from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Position,
    Organization,
    Position,
    Activity,
    TransferRecord,
    Participant,
    Notification,
    ActivityPhoto,
    Course,
    CourseTime,    
    CourseParticipant,
    CourseRecord,
)
from django.contrib.auth.models import User
from app.utils import get_person_or_org, if_image
from app.notification_utils import(
    notification_create,
    bulk_notification_create,
    notification_status_change,
)
from app.wechat_send import WechatApp, WechatMessageLevel
import io
import os
import base64
import qrcode

from random import sample
from datetime import datetime, timedelta
from boottest import local_dict
from django.db.models import Sum
from django.db.models import F

from app.scheduler import scheduler

hash_coder = MySHA256Hasher(local_dict["hash"]["base_hasher"])


