from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Organization,
    Activity,
    Notification,
    ActivityPhoto,
    Position,
    Participant,
    Course,
    CourseTime,
)
from app.utils import get_person_or_org
from app.notification_utils import(
    notification_create,
    notification_status_change,
)
from app.wechat_send import WechatApp, WechatMessageLevel
from app.activity_utils import (
    changeActivityStatus, 
    check_ac_time,
    notifyActivity,
)

from datetime import datetime, timedelta

from app.scheduler import scheduler


__all__ = [
    'course_activity_base_check',
    'create_single_course_activity',
    'modify_course_activity',
    'cancel_course_activity',
    'course_base_check',
    'create_course',
]


def course_activity_base_check(request):
    '''检查课程活动，是activity_base_check的简化版，失败时抛出AssertionError'''
    context = dict()

    # 读取活动名称和地点，检查合法性
    context["title"] = request.POST["title"]
    # context["introduction"] = request.POST["introduction"] # 暂定不需要简介
    context["location"] = request.POST["location"]
    assert len(context["title"]) > 0, "标题不能为空"
    # assert len(context["introduction"]) > 0 # 暂定不需要简介
    assert len(context["location"]) > 0, "地点不能为空"

    # 读取活动时间，检查合法性
    act_start = datetime.strptime(
        request.POST["lesson_start"], "%Y-%m-%d %H:%M")  # 活动开始时间
    act_end = datetime.strptime(
        request.POST["lesson_end"], "%Y-%m-%d %H:%M")  # 活动结束时间
    context["start"] = act_start
    context["end"] = act_end
    assert check_ac_time(act_start, act_end), "活动时间非法"

    # 默认需要签到
    context["need_checkin"] = True

    return context


def create_single_course_activity(request):
    '''
    创建单次课程活动，是create_activity的简化版
    '''
    context = course_activity_base_check(request)

    # 查找是否有类似活动存在
    old_ones = Activity.objects.activated().filter(
        title=context["title"],
        start=context["start"],
        # introduction=context["introduction"], # 暂定不需要简介
        location=context["location"],
        category=Activity.ActivityCategory.COURSE,  # 查重时要求是课程活动
    )
    if len(old_ones):
        assert len(old_ones) == 1, "创建活动时，已存在的相似活动不唯一"
        return old_ones[0].id, False

    # 获取默认审核老师
    default_examiner_name = get_setting("course/audit_teacher")
    examine_teacher = NaturalPerson.objects.get(
        name=default_examiner_name, identity=NaturalPerson.Identity.TEACHER)

    # 创建活动
    org = get_person_or_org(request.user, "Organization")
    activity = Activity.objects.create(
        title=context["title"],
        organization_id=org,
        examine_teacher=examine_teacher,
        # introduction=context["introduction"],  # 暂定不需要简介
        location=context["location"],
        start=context["start"],
        end=context["end"],
        category=Activity.ActivityCategory.COURSE,
        need_checkin=True,  # 默认需要签到

        # 因为目前没有报名环节，活动状态在活动开始前默认都是WAITING，按预审核活动的逻辑
        recorded=True,
        status=Activity.Status.WAITING,

        # capacity, URL, budget, YQPoint, bidding,
        # apply_reason, inner, source, end_before均为default
    )

    # 让课程小组成员参与本活动
    positions = Position.objects.activated().filter(org=activity.organization_id)
    for position in positions:
        Participant.objects.create(
            activity_id=activity, person_id=position.person,
            status=Participant.AttendStatus.APLLYSUCCESS,
        )
    activity.current_participants = len(positions)
    activity.save()

    # 通知课程小组成员
    notifyActivity(activity.id, "newActivity")

    # 引入定时任务：提前15min提醒、活动状态由WAITING变PROGRESSING再变END
    scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
                      run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
                      run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING])
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
                      run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END])
    activity.save()

    # 使用一张默认图片以便viewActivity, examineActivity等页面展示
    tmp_pic = '/static/assets/img/announcepics/1.JPG'
    ActivityPhoto.objects.create(
        image=tmp_pic, type=ActivityPhoto.PhotoType.ANNOUNCE, activity=activity)

    # 通知审核老师
    notification_create(
        receiver=examine_teacher.person_id,
        sender=request.user,
        typename=Notification.Type.NEEDDO,
        title=Notification.Title.VERIFY_INFORM,
        content="您有一个单次课程活动待审批",
        URL=f"/examineActivity/{activity.id}",
        relate_instance=activity,
        publish_to_wechat=True,
        publish_kws={"app": WechatApp.AUDIT},
    )

    return activity.id, True


def modify_course_activity(request, activity):
    '''
    修改单次课程活动信息，是modify_activity的简化版
    成功无返回值，失败返回错误消息
    '''
    # 课程活动无需报名，在开始前都是等待中的状态
    if activity.status != Activity.Status.WAITING:
        return "课程活动只有在等待状态才能修改。"

    context = course_activity_base_check(request)

    # 记录旧信息（以便发通知），写入新信息
    old_title = activity.title
    activity.title = context["title"]
    # activity.introduction = context["introduction"]# 暂定不需要简介
    old_location = activity.location
    activity.location = context["location"]
    old_start = activity.start
    activity.start = context["start"]
    old_end = activity.end
    activity.end = context["end"]
    activity.save()

    # 目前只要编辑了活动信息，无论活动处于什么状态，都通知全体选课同学
    # if activity.status != Activity.Status.APPLYING and activity.status != Activity.Status.WAITING:
    #     return

    # 写通知
    to_participants = [f"您参与的书院课程活动{old_title}发生变化"]
    if old_title != activity.title:
        to_participants.append(f"活动更名为{activity.title}")
    if old_location != activity.location:
        to_participants.append(f"活动地点修改为{activity.location}")
    if old_start != activity.start:
        to_participants.append(
            f"活动开始时间调整为{activity.start.strftime('%Y-%m-%d %H:%M')}")

    # 更新定时任务
    scheduler.add_job(notifyActivity, "date", id=f"activity_{activity.id}_remind",
                      run_date=activity.start - timedelta(minutes=15), args=[activity.id, "remind"], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.PROGRESSING}",
                      run_date=activity.start, args=[activity.id, Activity.Status.WAITING, Activity.Status.PROGRESSING], replace_existing=True)
    scheduler.add_job(changeActivityStatus, "date", id=f"activity_{activity.id}_{Activity.Status.END}",
                      run_date=activity.end, args=[activity.id, Activity.Status.PROGRESSING, Activity.Status.END], replace_existing=True)

    # 发通知
    notifyActivity(activity.id, "modification_par", "\n".join(to_participants))


def cancel_course_activity(request, activity):
    '''
    取消单次课程活动，是cancel_activity的简化版，在聚合页面被调用

    在聚合页面中，应确保activity是课程活动，并且应检查activity.status，
    如果不是WAITING或PROGRESSING，不应调用本函数

    成功无返回值，失败返回错误消息
    （或者也可以在聚合页面判断出来能不能取消）
    '''
    # 只有WAITING和PROGRESSING有可能修改
    if activity.status not in [
        Activity.Status.WAITING,
        Activity.Status.PROGRESSING,
    ]:
        return f"课程活动状态为{activity.get_status_display()}，不可取消。"

    # 课程活动已于一天前开始则不能取消，这一点也可以在聚合页面进行判断
    if activity.status == Activity.Status.PROGRESSING:
        if activity.start.day != datetime.now().day:
            return "课程活动已于一天前开始，不能取消。"

    # 取消活动
    activity.status = Activity.Status.CANCELED
    # 目前只要取消了活动信息，无论活动处于什么状态，都通知全体选课同学
    notifyActivity(activity.id, "modification_par",
                   f"您报名的书院课程活动{activity.title}已取消（活动原定开始于{activity.start.strftime('%Y-%m-%d %H:%M')}）。")

    # 删除老师的审核通知（如果有）
    notification = Notification.objects.get(
        relate_instance=activity,
        typename=Notification.Type.NEEDDO
    )
    notification_status_change(notification, Notification.Status.DELETE)

    # 取消定时任务
    scheduler.remove_job(f"activity_{activity.id}_remind")
    scheduler.remove_job(
        f"activity_{activity.id}_{Activity.Status.PROGRESSING}")
    scheduler.remove_job(f"activity_{activity.id}_{Activity.Status.END}")

    activity.save()


def course_base_check(request):
    context = dict()

    # name, introduction, classroom 创建时不能为空
    context["name"] = request.POST["name"]
    context["introduction"] = request.POST["introduction"]
    context["classroom"] = request.POST["classroom"]
    assert len(context["name"]) > 0
    assert len(context["introduction"]) > 0
    assert len(context["classroom"]) > 0

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

    # 每周课程时间
    course_starts = request.POST.getlist("start")
    course_ends = request.POST.getlist("end")
    course_starts = [datetime.strptime(course_start, "%Y-%m-%d %H:%M") for course_start in course_starts]
    course_ends = [datetime.strptime(course_end, "%Y-%m-%d %H:%M") for course_end in course_ends]
    for i in range(len(course_starts)):
        assert check_ac_time(course_starts[i], course_ends[i])
    context['course_starts'] = course_starts
    context['course_ends'] = course_ends

    org = get_person_or_org(request.user, "Organization")
    context['organization'] = org
    context['times'] = request.POST["times"]
    context['teacher'] = request.POST["teacher"]
    context['type'] = request.POST["type"]
    context["capacity"] = request.POST["capacity"]
    # context['current_participants'] = request.POST["current_participants"]
    context["photo"] = request.FILES.get("photo")
    return context


def create_course(request, course=None):
    '''
    检查课程，合法时寻找该课程，不存在时创建
    返回(course.id, created)
    '''
    context = course_base_check(request)
    
    # 编辑已有课程
    if course is not None:
        course_time = course.time_set.all()
        course_time.delete()

        course.update(
            name=context["name"],
            organization=context['organization'],
            # year=context['year'],
            # semester=context['semester'],
            times=context['times'],
            classroom=context["classroom"],
            teacher=context['teacher'],
            stage1_start=context['stage1_start'],
            stage1_end=context['stage1_end'],
            stage2_start=context['stage2_start'],
            stage2_end=context['stage2_end'],
            # bidding=context["bidding"],
            introduction=context["introduction"],
            # status=context['status'],
            type=context['type'],
            capacity=context["capacity"],
            # current_participants=context['current_participants'],
            photo=context['photo'],
            )

        for i in range(len(context['course_starts'])):
            CourseTime.objects.create(
                course=course,
                start=context['course_starts'][i],
                end=context['course_ends'][i],
                end_week=context['times'],
            )

    # 创建新课程
    else:
        # 查找是否有类似课程存在
        old_ones = Course.objects.activated().filter(
            name=context["name"],
            teacher=context['teacher'],
            classroom=context["classroom"],
        )
        if len(old_ones):
            assert len(old_ones) == 1, "创建课程时，已存在的相似课程不唯一"
            return old_ones[0].id, False
        
        # 检查完毕，创建课程
        course = Course.objects.create(
                        name=context["name"],
                        organization=context['organization'],
                        # year=context['year'],
                        # semester=context['semester'],
                        times=context['times'],
                        classroom=context["classroom"],
                        teacher=context['teacher'],
                        stage1_start=context['stage1_start'],
                        stage1_end=context['stage1_end'],
                        stage2_start=context['stage2_start'],
                        stage2_end=context['stage2_end'],
                        # bidding=context["bidding"],
                        introduction=context["introduction"],
                        # status=context['status'],
                        type=context['type'],
                        capacity=context["capacity"],
                        # current_participants=context['current_participants'],
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
        
        for i in range(len(context['course_starts'])):
            CourseTime.objects.create(
                course=course,
                start=context['course_starts'][i],
                end=context['course_ends'][i],
                end_week=context['times'],
            )

    return course.id, True
