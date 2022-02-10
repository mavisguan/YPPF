from app.utils_dependency import *
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


# 时间合法性的检查，检查时间是否在当前时间的一个月以内，并且检查开始的时间是否早于结束的时间，
def check_ac_time(start_time, end_time):
    now_time = datetime.now()
    month_late = now_time + timedelta(days=30)
    if not start_time < end_time:
        return False
    if now_time < start_time < month_late:
        return True  # 时间所处范围正确

    return False


def create_course(request, course=None):
    '''
    检查课程，合法时寻找该课程，不存在时创建
    返回(course.id, created)
    '''

    context = dict()

    # title, introduction, location 创建时不能为空
    context["title"] = request.POST["title"]
    context["introduction"] = request.POST["introduction"]
    context["location"] = request.POST["location"]
    assert len(context["title"]) > 0
    assert len(context["introduction"]) > 0
    assert len(context["location"]) > 0

    # 时间
    stage1_start = datetime.strptime(request.POST["stage1_start"], "%Y-%m-%d %H:%M")  # 预选开始时间
    stage1_end = datetime.strptime(request.POST["stage1_end"], "%Y-%m-%d %H:%M")  # 预选结束时间
    stage2_start = datetime.strptime(request.POST["stage2_start"], "%Y-%m-%d %H:%M")  # 补退选开始时间
    stage2_end = datetime.strptime(request.POST["stage2_end"], "%Y-%m-%d %H:%M")  # 补退选结束时间
    context["stage1_start"] = stage1_start
    context["stage1_end"] = stage1_end
    context["stage2_start"] = stage2_start
    context["stage2_end"] = stage2_end
    assert check_ac_time(stage1_start, stage1_end)
    assert check_ac_time(stage2_start, stage2_end)
    # 预选开始时间和结束时间不应该相隔太近
    assert stage1_end > stage1_start + timedelta(days=7)
    # 预选结束时间和补退选开始时间不应该相隔太近
    assert stage2_start > stage1_end + timedelta(days=3)

    # 每周课程时间。这里是不是改成列表比较好？后面创建太麻烦了先写一个示例，要改了我再加上
    course1_start = datetime.strptime(request.POST["course1_start"], "%Y-%m-%d %H:%M")  # 第1节课开始时间
    course1_end = datetime.strptime(request.POST["course1_end"], "%Y-%m-%d %H:%M")  # 结束时间
    course2_start = datetime.strptime(request.POST["course2_start"], "%Y-%m-%d %H:%M")  # 第2节课开始时间
    course2_end = datetime.strptime(request.POST["course2_end"], "%Y-%m-%d %H:%M")  # 结束时间
    course3_start = datetime.strptime(request.POST["course3_start"], "%Y-%m-%d %H:%M")  # 第3节课开始时间
    course3_end = datetime.strptime(request.POST["course3_end"], "%Y-%m-%d %H:%M")  # 结束时间

    org = get_person_or_org(request.user, "Organization")
    context['organization'] = org
    context['times'] = request.POST["times"]
    context['teacher'] = request.POST["teacher"]
    # context['bidding'] = request.POST["bidding"]
    context['status'] = Course.status.WAITING
    context['type'] = request.POST["type"]
    context["capacity"] = request.POST["capacity"]
    # context['current_participants'] = request.POST["current_participants"]
    context["photo"] = request.FILES.get("photo")
    
    # 编辑已有课程
    if course is not None:
        course_time = course.time_set.all()
        course_time.delete()

        course.update(
            title=context["title"],
            organization=context['organization'],
            # year=context['year'],
            # semester=context['semester'],
            times=context['times'],
            location=context["location"],
            teacher=context['teacher'],
            stage1_start=context['stage1_start'],
            stage1_end=context['stage1_end'],
            stage2_start=context['stage2_start'],
            stage2_end=context['stage2_end'],
            # bidding=context["bidding"],
            introduction=context["introduction"],
            status=context['status'],
            type=context['type'],
            capacity=context["capacity"],
            # current_participants=context['current_participants'],
            photo=context['photo'],
            )
        course.save()

        course_time = CourseTime.objects.create(
            course=course,
            start=course1_start,
            end=course1_end,
        )

    # 创建新课程
    else:
        # 查找是否有类似课程存在
        old_ones = Course.objects.activated().filter(
            title=context["title"],
            year=context['year'],
            semester=context['semester'],
            teacher=context['teacher'],
            location=context["location"],
        )
        if len(old_ones):
            assert len(old_ones) == 1, "创建课程时，已存在的相似课程不唯一"
            return old_ones[0].id, False

        # 检查完毕，创建课程
        course = Course.objects.create(
                        title=context["title"],
                        organization=context['organization'],
                        year=context['year'],
                        semester=context['semester'],
                        times=context['times'],
                        location=context["location"],
                        teacher=context['teacher'],
                        stage1_start=context['stage1_start'],
                        stage1_end=context['stage1_end'],
                        stage2_start=context['stage2_start'],
                        stage2_end=context['stage2_end'],
                        bidding=context["bidding"],
                        introduction=context["introduction"],
                        status=context['status'],
                        type=context['type'],
                        capacity=context["capacity"],
                        current_participants=context['current_participants'],
                        photo=context['photo'],
                    )

        # 定时任务和微信消息有关吗，我还没了解怎么发微信消息orz不过定时任务还是能写出来的……应该

        # scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
        #     run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
        # # 活动状态修改
        # scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.WAITING}",
        #     run_date=activity.apply_end, args=[activity.id, Activity.Status.APPLYING, Activity.Status.WAITING])
        # scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
        #     run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING])
        # scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
        #     run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END])

        course.save()

        course_time = CourseTime.objects.create(
            course=course,
            start=course1_start,
            end=course1_end,
        )

    return course.id, True
