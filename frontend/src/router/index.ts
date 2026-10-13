import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import { rememberedReadingCaseId } from '@/utils/reading-case'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
    meta: { title: '登录', public: true }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/login/register.vue'),
    meta: { title: '注册', public: true }
  },
  {
    path: '/apply-student',
    name: 'ApplyStudent',
    component: () => import('@/views/login/apply-student.vue'),
    meta: { title: '申请学员账号', public: true }
  },
  {
    // OIDC 授权码回调：Keycloak 登录完成后跳回本页换取令牌
    path: '/oidc/callback',
    name: 'OidcCallback',
    component: () => import('@/views/login/oidc-callback.vue'),
    meta: { title: '登录中', public: true }
  },

  {
    // LTI 启动落地页：从 Moodle 等 LMS 进来时的第一站。
    // public 是必须的 —— 此刻本系统还没有登录态，令牌正要在这里落地。
    path: '/lti-entry',
    name: 'LtiEntry',
    component: () => import('@/views/login/lti-entry.vue'),
    meta: { title: '正在进入', public: true }
  },
  {
    // Cornerstone3D 技术验证页（替换阅片内核前的最小验证，非正式功能）
    path: '/spike/cornerstone',
    name: 'CornerstoneSpike',
    component: () => import('@/views/spike/cornerstone-spike.vue'),
    meta: { title: 'Cornerstone3D 验证' }
  },
  {
    // 阅片内核自检（web: 加载器与坐标往返，非正式功能）
    path: '/spike/viewport-check',
    name: 'ViewportCheck',
    component: () => import('@/views/spike/viewport-check.vue'),
    // public：自检只渲染一张静态图并做坐标换算，不读任何业务数据，
    // 无需登录态。加它是为了能在 CI / 无头浏览器里直接跑。
    meta: { title: '阅片内核自检', public: true }
  },
  {
    // 阅片组件自检（替换后的 CoreRetinaStation，非正式功能）
    path: '/spike/station-check',
    name: 'StationCheck',
    component: () => import('@/views/spike/station-check.vue'),
    meta: { title: '阅片组件自检', public: true }
  },  {
    // 首页：病患进报告页，教师/学员进培训端（筛查从侧栏「AI 批量筛查」进入）
    path: '/',
    redirect: () => {
      try {
        const u = JSON.parse(localStorage.getItem('huiyan_user') || '{}')
        return u?.role === 'patient' ? '/patient/reports' : '/training'
      } catch {
        return '/training'
      }
    }
  },

  /* ============================================================
   * 体检筛查端 —— 已恢复启用（教师/管理员专用，学员/患者不可见）
   * DiagnosisUpload 已对接 CSU-EYES 真实算法（MA检测 / DR分级 / 综合诊断）
   * ============================================================ */
  {
    path: '/screening',
    component: () => import('@/layout/portals/ScreeningPortal.vue'),
    meta: { scene: 'screening', deniedRoles: ['trainee', 'patient'] },
    // 批量筛查已并入教师门户（/training/screening），旧链接自动跳转，避免切换门户后侧栏整体消失。
    redirect: '/training/screening',
    children: [
      { path: 'dashboard', redirect: '/training/screening' },
      // 筛查记录检索与病例中心数据源不同，本期保留在筛查门户内。
      { path: 'list', name: 'ScreeningList', component: () => import('@/views/screening/case-search.vue'), meta: { title: '筛查记录检索' } },
      { path: 'profile', redirect: '/training/profile' }
    ]
  },

  /* ============================================================
   * 医学培训端（深色主题）— 单端口侧边栏布局
   * 子页：病例库 / 阅片标注 / 自主练习 / 学习资料 / 个人中心 / 管理后台
   * ============================================================ */
  {
    path: '/training',
    component: () => import('@/layout/portals/TrainingPortal.vue'),
    meta: { scene: 'training' },
    redirect: (to) => ({ path: '/training/home', query: to.query }),
    children: [
      {
        path: 'home',
        name: 'TrainingHome',
        component: () => import('@/views/training/home.vue'),
        meta: { title: '首页', allowedRoles: ['admin', 'doctor', 'trainee'] }
      },
      {
        path: 'cases',
        name: 'TrainingCases',
        component: () => import('@/views/case-browse/index.vue'),
        meta: {
          title: '病例中心',
          allowedRoles: ['admin', 'doctor', 'trainee']
        },
        // 教学分享已独立成 /training/teaching-share，旧书签跳过去。
        beforeEnter: (to) => {
          if (String(to.query.tab || '') !== 'my-shares') return true
          const { tab: _tab, ...rest } = to.query
          return { path: '/training/teaching-share', query: rest, replace: true }
        }
      },
      {
        path: 'reading',
        name: 'TrainingReading',
        component: () => import('@/views/reading/index.vue'),
        meta: { title: '双眼阅片工作台' },
        // 侧栏「阅片工作台」只有路径、没有病例编号。从病例库回来时把上次的编号补上，
        // 否则页面没有 caseId，影像请求发不出去。
        beforeEnter: (to) => {
          const tab = String(to.query.tab || '')
          // 旧书签 tab=quality 统一改成 tab=review，避免和「图像质控」混淆。
          if (tab === 'quality') {
            return { path: to.path, query: { ...to.query, tab: 'review' }, replace: true }
          }
          if (to.query.caseId || to.query.recordId) return true
          if (tab === 'review') return true
          const saved = rememberedReadingCaseId()
          if (!saved) return true
          return {
            path: to.path,
            query: { ...to.query, caseId: String(saved) },
            replace: true
          }
        }
      },
      {
        path: 'practice',
        name: 'TrainingPractice',
        component: () => import('@/views/practice/index.vue'),
        meta: { title: '病例学习' }
      },
      {
        path: 'my-reviews',
        name: 'StudentReviews',
        component: () => import('@/views/training/student-reviews.vue'),
        meta: { title: '教师评定', allowedRoles: ['trainee'] }
      },
      {
        path: 'practice/workstation',
        name: 'TrainingPracticeWorkstation',
        component: () => import('@/views/practice/workstation.vue'),
        meta: { title: '病例学习' },
        beforeEnter: (to) => {
          if (!to.query.caseId || !to.query.sessionId) {
            ElMessage.warning('请从病例学习进入')
            return { path: '/training/practice' }
          }
        }
      },
      {
        path: 'class',
        name: 'TrainingClass',
        component: () => import('@/views/training/class-students.vue'),
        meta: { title: '班级与学员维护', allowedRoles: ['admin', 'doctor'] }
      },
      {
        path: 'exams',
        name: 'FormalExams',
        component: () => import('@/views/training/exams.vue'),
        meta: { title: '正式考核与试卷', allowedRoles: ['admin', 'doctor'] }
      },
      {
        path: 'teaching-share',
        name: 'TeachingShare',
        component: () => import('@/views/training/teaching-share.vue'),
        meta: { title: '教学分享', allowedRoles: ['admin', 'doctor'] }
      },
      {
        path: 'screening',
        name: 'TrainingScreening',
        component: () => import('@/layout/portals/ScreeningWorkspace.vue'),
        props: { section: 'upload' },
        meta: { title: 'AI 批量筛查', allowedRoles: ['admin', 'doctor'] }
      },
      {
        path: 'ai-builder',
        name: 'AiCaseBuilder',
        redirect: { path: '/training/cases', query: { tab: 'ai-builder' } },
        meta: { title: 'AI 智能建案', allowedRoles: ['admin', 'doctor'] }
      },
      {
        path: 'review',
        redirect: { path: '/training/reading', query: { tab: 'review' } },
        meta: { title: '作业批阅', allowedRoles: ['admin', 'doctor'] }
      },
      {
        path: 'student-teaching',
        name: 'StudentTeaching',
        component: () => import('@/views/training/student-teaching.vue'),
        meta: { title: '教师演示病例', allowedRoles: ['admin', 'doctor', 'trainee'] }
      },
      {
        path: 'learning',
        name: 'TrainingLearning',
        component: () => import('@/views/learning/index.vue'),
        meta: { title: '学习资料与笔记' }
      },
      {
        path: 'admin-notes',
        name: 'TrainingAdminNotes',
        component: () => import('@/views/learning/admin-notes.vue'),
        meta: { title: '笔记管理（审核视图）', allowedRoles: ['admin'] }
      },
      {
        path: 'notices',
        name: 'TrainingNotices',
        component: () => import('@/views/notices/NotificationInbox.vue'),
        meta: { title: '通知' }
      },
      {
        path: 'profile',
        name: 'TrainingProfile',
        component: () => import('@/views/profile/index.vue'),
        meta: { title: '个人中心' }
      },
      {
        path: 'admin',
        name: 'TrainingAdmin',
        component: () => import('@/views/admin/index.vue'),
        meta: { title: '平台管理后台', allowedRoles: ['admin'] }
      }
    ]
  },

  /* ============================================================
   * 个人中心（独立访问点，未带端口主题）
   * ============================================================ */
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('@/views/profile/index.vue'),
    meta: { title: '个人中心' }
  },

  /* ============================================================
   * PATIENT 端门户（浅色主题）— 单端口侧边栏布局
   * 子页：我的病例 / 个人中心 / 申请权限
   * ============================================================ */
  {
    path: '/patient',
    component: () => import('@/layout/portals/PatientPortal.vue'),
    meta: { allowedRoles: ['patient'] },
    redirect: '/patient/reports',
    children: [
      {
        path: 'reports',
        name: 'PatientPortalReports',
        component: () => import('@/views/patient/reports.vue'),
        meta: { title: '我的病例' }
      },
      {
        path: 'profile',
        name: 'PatientProfile',
        component: () => import('@/views/patient/profile.vue'),
        meta: { title: '个人中心' }
      },
      {
        path: 'apply',
        name: 'PatientApply',
        component: () => import('@/views/patient/apply.vue'),
        meta: { title: '申请权限' }
      }
    ]
  },

  /* ============================================================
   * 兼容老路径：原顶层独立模块跳转，统一重定向到培训端口对应页
   * ============================================================ */
  { path: '/case-browse', redirect: '/training/cases' },
  { path: '/reading', redirect: (to) => ({ path: '/training/reading', query: to.query }) },
  { path: '/practice', redirect: '/training/practice' },
  { path: '/practice/workstation', redirect: (to) => ({ path: '/training/practice/workstation', query: to.query }) },
  { path: '/learning', redirect: '/training/learning' },
  { path: '/admin', redirect: '/training/admin' },

  {
    path: '/:pathMatch(.*)*',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

const TOKEN_KEY = 'huiyan_token'
const USER_KEY = 'huiyan_user'

const getRole = (): string => {
  try {
    const u = JSON.parse(localStorage.getItem(USER_KEY) || '{}')
    return (u?.role as string) || ''
  } catch {
    return ''
  }
}

const homePathForRole = (role: string): string => {
  if (role === 'patient') return '/patient/reports'
  if (role === 'trainee') return '/training'
  if (role === 'admin' || role === 'doctor') return '/'
  return '/'
}

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (to.meta.title) {
    document.title = `${to.meta.title} · 慧眼 AI 教学实训平台`
  }
  if (to.meta.public) {
    next()
    return
  }
  if (!token) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  // 自顶向下收集本路径上所有的 deniedRoles / allowedRoles 元数据
  const deniedRoles = new Set<string>()
  const allowedRoles = new Set<string>()
  for (const m of to.matched) {
    ;(m.meta?.deniedRoles as string[] | undefined)?.forEach((r) => deniedRoles.add(r))
    ;(m.meta?.allowedRoles as string[] | undefined)?.forEach((r) => allowedRoles.add(r))
  }

  const role = getRole()

  // 管理员重置临时密码后，除个人中心改密外一律拦下
  try {
    const u = JSON.parse(localStorage.getItem(USER_KEY) || '{}')
    if (u?.mustChangePassword) {
      const allowed =
        to.path.endsWith('/profile') ||
        to.path === '/profile' ||
        to.path === '/login'
      if (!allowed) {
        ElMessage.warning('请先修改临时密码后再使用系统')
        next({
          path: role === 'patient' ? '/patient/profile' : '/training/profile',
          query: { forcePwd: '1' }
        })
        return
      }
    }
  } catch {
    /* 解析失败按未强制改密处理 */
  }

  if (deniedRoles.has(role) || (allowedRoles.size > 0 && !allowedRoles.has(role))) {
    const home = homePathForRole(role)
    if (to.path === home) {
      // 防止循环重定向
      next()
      return
    }
    next({ path: home })
    return
  }
  next()
})

export default router
