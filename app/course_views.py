from app.views_dependency import *
from app.models import (
    NaturalPerson,
    Activity,
    Course,
)
from app.course_utils import (
    create_single_course_activity,
    modify_course_activity,
    create_course,
)
from app.utils import (
    get_person_or_org,
)

from datetime import datetime, timedelta
from django.db import transaction

__all__ = [
    'editCourseActivity', 
    'addSingleCourseActivity',
    'addCourse',
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[editCourseActivity]', record_user=True)
def editCourseActivity(request, aid):
    """
    编辑单次书院课程活动，addActivity的简化版
    """
    # 检查用户身份
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        me = utils.get_person_or_org(request.user, user_type)  # 这里的me应该为小组账户
        aid = int(aid)
        activity = Activity.objects.get(id=aid)
        if user_type == "Person":
            html_display = utils.user_login_org(
                request, activity.organization_id)
            if html_display['warn_code'] == 1:
                return redirect(message_url(wrong(html_display["warn_message"])))
            else:  # 成功以小组账号登陆
                # 防止后边有使用，因此需要赋值
                user_type = "Organization"
                request.user = activity.organization_id.organization_id  # 小组对应user
                me = activity.organization_id  # 小组
        if activity.organization_id != me:
            return redirect(message_url(wrong("无法修改其他课程小组的活动!")))
        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    # 这个页面只能修改书院课程活动(category=1)
    if activity.category != Activity.ActivityCategory.COURSE:
        return redirect(message_url(wrong('当前活动不是书院课程活动!'),
                                    f'/viewActivity/{activity.id}'))
    # 课程活动无需报名，在开始前都是等待中的状态
    if activity.status != Activity.Status.WAITING:
        return redirect(message_url(wrong('当前活动状态不允许修改!'),
                                    f'/viewActivity/{activity.id}'))

    if request.method == "POST" and request.POST:
        # 修改活动
        try:
            # 只能修改自己的活动
            with transaction.atomic():
                activity = Activity.objects.select_for_update().get(id=aid)
                org = get_person_or_org(request.user, "Organization")
                assert activity.organization_id == org
                modify_course_activity(request, activity)
            html_display["warn_msg"] = "修改成功。"
            html_display["warn_code"] = 2
        except Exception as e:
            log.record_traceback(request, e)
            return EXCEPT_REDIRECT

    # 前端使用量
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava()
    bar_display = utils.get_sidebar_and_navbar(request.user, "修改单次课程活动")

    # 前端使用量，均可编辑
    title = utils.escape_for_templates(activity.title)
    location = utils.escape_for_templates(activity.location)
    start = activity.start.strftime("%Y-%m-%d %H:%M")
    end = activity.end.strftime("%Y-%m-%d %H:%M")
    # introduction = escape_for_templates(activity.introduction) # 暂定不需要简介
    edit = True  # 前端据此区分是编辑还是创建

    return render(request, "lesson_add.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='views[addSingleCourseActivity]', record_user=True)
def addSingleCourseActivity(request):
    """
    创建单次书院课程活动，addActivity的简化版
    """
    # 检查用户身份
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        me = utils.get_person_or_org(request.user, user_type)  # 这里的me应该为小组账户
        if user_type != "Organization":
            return redirect(message_url(wrong('书院课程小组账号才能开设课程活动!')))
        if me.oname == YQP_ONAME:
            return redirect("/showActivity")  # TODO: 可以重定向到书院课程聚合页面
        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    if request.method == "POST" and request.POST:
        # 创建活动
        try:
            with transaction.atomic():
                aid, created = create_single_course_activity(request)
                if not created:
                    return redirect(message_url(
                        succeed('存在信息相同的课程活动，已为您自动跳转!'),
                        f'/viewActivity/{aid}'))
                return redirect(f"/editCourseActivity/{aid}")
        except Exception as e:
            log.record_traceback(request, e)
            return EXCEPT_REDIRECT

    # 前端使用量
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava()
    bar_display = utils.get_sidebar_and_navbar(request.user, "发起单次课程活动")
    edit = False  # 前端据此区分是编辑还是创建

    return render(request, "lesson_add.html", locals())


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='course_views[addCourse]', record_user=True)
def addCourse(request, cid=None):
    """
    发起课程页
    ---------------
    页面逻辑：

    该函数处理 GET, POST 两种请求，发起和修改两类操作
    1. 访问 /addCourse/ 时，为创建操作，要求用户是小组；
    2. 访问 /editCourse/aid 时，为编辑操作，要求用户是该活动的发起者
    3. GET 请求创建活动的界面，placeholder 为 prompt
    4. GET 请求编辑活动的界面，表单的 placeholder 会被修改为活动的旧值。
    """
    # TODO 定时任务

    # 检查：不是超级用户，必须是小组，修改是必须是自己
    try:
        valid, user_type, html_display = utils.check_user_type(request.user)
        # assert valid  已经在check_user_access检查过了
        me = utils.get_person_or_org(request.user, user_type) # 这里的me应该为小组账户
        if cid is None:
            if user_type != "Organization" or me.otype.otype_name != "书院课程":
                return redirect(message_url(wrong('书院课程账号才能发起课程!')))
            edit = False
        else:
            cid = int(cid)
            course = Course.objects.get(id=cid)
            if user_type == "Person":
                html_display=utils.user_login_org(request, course.organization)
                if html_display['warn_code'] == 1:
                    return redirect(message_url(wrong(html_display["warn_message"])))
                else: # 成功以小组账号登陆
                    # 防止后边有使用，因此需要赋值
                    user_type = "Organization"
                    request.user = course.organization.organization_id #小组对应user
                    me = course.organization #小组
            if course.organization != me:
                return redirect(message_url(wrong("无法修改其他小组的课程!")))
            edit = True
        html_display["is_myself"] = True
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    
    # 处理 POST 请求
    # 在这个界面，不会返回render，而是直接跳转到viewCourse，可以不设计bar_display
    if request.method == "POST" and request.POST:
        if not edit:
            try:
                with transaction.atomic():
                    cid, created = create_course(request)
                    if not created:
                        return redirect(message_url(
                            succeed('存在信息相同的课程，已为您自动跳转!'),
                            f'/viewCourse/{cid}'))
                    return redirect(f"/editCourse/{cid}")
            except Exception as e:
                log.record_traceback(request, e)
                return EXCEPT_REDIRECT
        else:
            # 仅未开始选课阶段可以修改
            if course.status != Course.Status.WAITING:
                return redirect(message_url(wrong('当前课程状态不允许修改!'),
                                            f'/viewCourse/{course.id}'))
            
            try:
                # 只能修改自己的课程
                with transaction.atomic():
                    course = Course.objects.select_for_update().get(id=cid)
                    org = utils.get_person_or_org(request.user, "Organization")
                    assert course.organization == org
                    create_course(request, course)
                html_display["warn_msg"] = "修改成功。"
                html_display["warn_code"] = 2
            except Exception as e:
                log.record_traceback(request, e)
                return EXCEPT_REDIRECT

    
    # 下面的操作基本如无特殊说明，都是准备前端使用量
    html_display["applicant_name"] = me.oname
    html_display["app_avatar_path"] = me.get_user_ava() 

    try:
        if edit and course.status == Course.Status.WAITING:
            editable = True

            name = utils.escape_for_templates(course.name)
            organization = course.organization
            year = course.year
            semester = utils.escape_for_templates(course.semester)
            times = course.times
            classroom = utils.escape_for_templates(course.classroom)
            teacher = utils.escape_for_templates(course.teacher)
            stage1_start = course.stage1_start.strftime("%Y-%m-%d %H:%M")
            stage1_end = course.stage1_end.strftime("%Y-%m-%d %H:%M")
            stage2_start = course.stage2_start.strftime("%Y-%m-%d %H:%M")
            stage2_end = course.stage2_end.strftime("%Y-%m-%d %H:%M")
            course_time = course.time_set.all()
            bidding = course.bidding
            introduction = utils.escape_for_templates(course.introduction)
            status = course.status
            type_name = course.get_type_display
            capacity = course.capacity
            current_participants = course.current_participants
            photo = str(course.photo)
    except Exception as e:
        log.record_traceback(request, e)
        return EXCEPT_REDIRECT

    html_display["today"] = datetime.now().strftime("%Y-%m-%d")
    if not edit:
        bar_display = utils.get_sidebar_and_navbar(request.user, "发起课程")
    else:
        bar_display = utils.get_sidebar_and_navbar(request.user, "修改课程")
    
    return render(request, "register_course.html", locals())
