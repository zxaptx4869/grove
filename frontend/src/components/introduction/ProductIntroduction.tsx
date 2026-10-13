import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowDown,
  ArrowRight,
  BookOpen,
  Check,
  CheckCheck,
  ChevronRight,
  FileText,
  Folder,
  FolderTree,
  Layers,
  MessageSquare,
  Monitor,
  ScanLine,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Trees,
} from 'lucide-react'
import { Button } from '@/components/ui/button'

const capabilities = [
  {
    id: 'organize',
    icon: ScanLine,
    label: 'AI 提取与归属推荐',
    title: '交进来的是材料，留下来的是知识。',
    description:
      'AI 从截图与文字中提取要点，结合项目背景推荐项目和目录。你可以对照原文修改、采纳或拒绝，确认后再成为正式知识。',
  },
  {
    id: 'structure',
    icon: FolderTree,
    label: 'AI 目录共创',
    title: '先有适合自己的框架，再有目标地学习。',
    description:
      '从你的目标、基础和关注点出发，与 AI 一起生成目录草稿。通过对话调整范围和层级，由你确认采用的结构。',
  },
  {
    id: 'agent',
    icon: MessageSquare,
    label: '知识 Agent 协助',
    title: '不必记住存在哪里，描述你要找什么。',
    description:
      '让 Agent 帮你查找已有知识、理解内容和继续追问。涉及个人知识的回答保留引用，让结论能回到原始材料核对。',
  },
] as const

function Brand() {
  return (
    <span className="intro-brand">
      <Trees aria-hidden="true" />
      <span>
        知林 <span className="intro-brand-english">Grove</span>
      </span>
    </span>
  )
}

function RecommendationExample() {
  return (
    <div className="intro-organize-example">
      <div className="intro-source-paper">
        <span className="intro-example-label">
          <FileText size={15} aria-hidden="true" /> 原始材料 · 文字节选
        </span>
        <h4>关于 React 重复渲染的笔记</h4>
        <p>先用 Profiler 定位渲染开销，再决定是否优化。</p>
        <p>memo 的效果取决于 props 是否稳定。每次创建新的对象或函数，可能让缓存失效。</p>
        <div className="intro-paper-lines" aria-hidden="true">
          <span />
          <span />
        </div>
      </div>
      <ArrowRight className="intro-example-arrow" size={22} aria-hidden="true" />
      <div className="intro-candidate-example">
        <span className="intro-example-label intro-ai-label">
          <Sparkles size={15} aria-hidden="true" /> AI 候选 · 待确认
        </span>
        <h4>优化前，先定位渲染开销</h4>
        <p>使用 Profiler 找到耗时的渲染，再判断是否需要优化。</p>
        <div className="intro-recommendation">
          <span>推荐项目</span>
          <strong>
            <Folder size={14} aria-hidden="true" /> 前端学习
          </strong>
        </div>
        <div className="intro-recommendation">
          <span>推荐目录</span>
          <strong>
            React <ChevronRight size={12} aria-hidden="true" /> 性能优化
          </strong>
        </div>
        <div className="intro-human-confirm">
          <ShieldCheck size={16} aria-hidden="true" /> 由你确认内容与归属后，进入正式知识库
        </div>
      </div>
    </div>
  )
}

function DirectoryExample() {
  return (
    <div className="intro-directory-example">
      <div className="intro-dialogue-fragment">
        <span className="intro-example-label">
          <MessageSquare size={15} aria-hidden="true" /> 你的学习目标
        </span>
        <p>“我想了解家庭装修，几乎没有基础。先关注开工前准备，材料选购以后再细化。”</p>
        <div className="intro-context-tags">
          <span>从零开始</span>
          <span>聚焦前期准备</span>
          <span>按需调整</span>
        </div>
      </div>
      <div className="intro-directory-tree">
        <span className="intro-example-label intro-ai-label">
          <FolderTree size={15} aria-hidden="true" /> AI 目录草稿 · 待确认
        </span>
        <strong>
          <Folder size={16} aria-hidden="true" /> 我的装修准备
        </strong>
        <ul>
          <li>
            01 <span>需求与预算</span>
            <small>明确优先级，了解费用构成</small>
          </li>
          <li>
            02 <span>流程与协作</span>
            <small>认识阶段，选择合作方式</small>
          </li>
          <li>
            03 <span>开工前检查</span>
            <small>核对方案、合同与准备事项</small>
          </li>
        </ul>
        <p>
          <Check size={14} aria-hidden="true" /> 继续对话调整，由你确认采用
        </p>
      </div>
    </div>
  )
}

function AgentExample() {
  return (
    <div className="intro-agent-example">
      <div className="intro-agent-question">
        <span>你</span>
        <p>我之前收藏的 React 性能优化经验里，哪些与重复渲染有关？</p>
      </div>
      <div className="intro-agent-answer">
        <span className="intro-example-label">
          <Sparkles size={15} aria-hidden="true" /> Grove · 基于已有知识的回答示例
        </span>
        <p>可以先从这两个方面检查：</p>
        <ol>
          <li>
            <strong>定位渲染开销。</strong>先用 Profiler 找到耗时的渲染，判断优化是否必要。
            <sup>［1］</sup>
          </li>
          <li>
            <strong>检查 props 稳定性。</strong>传入新建的对象或函数，可能影响 memo 的效果。
            <sup>［2］</sup>
          </li>
        </ol>
        <div className="intro-citation-example">
          <BookOpen size={16} aria-hidden="true" />
          <div>
            <strong>引用：React 重复渲染笔记</strong>
            <span>正式知识 → 来源材料 · 可回溯核对</span>
          </div>
          <span className="intro-citation-count">2 条引用</span>
        </div>
      </div>
    </div>
  )
}

export function ProductIntroduction({ login }: { login: ReactNode }) {
  const [selected, setSelected] = useState(0)
  const capability = capabilities[selected]

  return (
    <div className="public-intro">
      <a className="intro-skip-link" href="#intro-main">
        跳到产品介绍
      </a>
      <header className="intro-header">
        <div className="intro-container intro-header-inner">
          <Link to="/login" aria-label="知林 Grove 首页">
            <Brand />
          </Link>
          <nav aria-label="产品介绍导航">
            <a href="#scenarios">使用场景</a>
            <a href="#capabilities">AI 能力</a>
            <a href="#devices">多端协作</a>
            <a href="#engineering">设计与实现</a>
          </nav>
          <a className="intro-header-login" href="#login">
            {login ? '登录工作台' : '电脑端使用'}
            <ArrowRight size={15} aria-hidden="true" />
          </a>
        </div>
      </header>

      <main id="intro-main" className="intro-container" tabIndex={-1}>
        <section className="intro-hero" aria-labelledby="intro-title">
          <div className="intro-hero-copy">
            <p className="intro-eyebrow">
              <span /> AI 知识共创工具
            </p>
            <h1 id="intro-title">
              让零散知识<span>找得到，</span>
              <br />
              让陌生领域<span>学得有方向。</span>
            </h1>
            <p className="intro-hero-description">
              收藏过的经验，用时不必再翻找。想学习的新领域，
              <br className="intro-desktop-break" />
              从适合自己的框架开始。
            </p>
            <p className="intro-hero-detail">
              用 AI 整理材料、推荐归属、共创目录，
              <br className="intro-desktop-break" />
              再让知识 Agent 帮你查找、理解和使用积累的内容。
            </p>
            <Button asChild size="lg" className="intro-hero-action">
              <a href="#scenarios">
                看看 Grove 如何帮助你
                <ArrowDown aria-hidden="true" />
              </a>
            </Button>
            <p className="intro-trust-line">
              <ShieldCheck size={16} aria-hidden="true" /> AI 协助整理与共创，你掌握确认权。
            </p>
          </div>
          <aside
            id="login"
            className={login ? 'intro-login-card' : 'intro-mobile-notice'}
            aria-label={login ? '登录工作台' : '电脑端使用提示'}
          >
            {login ? (
              <>
                <div className="intro-login-mark">
                  <Trees size={24} aria-hidden="true" />
                </div>
                {login}
                <div className="intro-login-note">
                  <Layers size={15} aria-hidden="true" /> 一个账号，连接你的多端知识积累
                </div>
              </>
            ) : (
              <>
                <Monitor size={22} aria-hidden="true" />
                <div>
                  <strong>在电脑端登录，开始整理</strong>
                  <p>这里可以了解 Grove。完整知识工作台请在电脑端打开。</p>
                </div>
              </>
            )}
          </aside>
        </section>

        <div className="intro-workflow" aria-label="知识整理流程">
          <span>从一条材料，到一次有依据的回答</span>
          <ol>
            {['多端采集', 'AI 整理与推荐', '你来确认', 'Agent 协助使用'].map((step, index) => (
              <li key={step}>
                <small>0{index + 1}</small>
                {step}
                {index < 3 && <ChevronRight size={15} aria-hidden="true" />}
              </li>
            ))}
          </ol>
        </div>

        <section id="scenarios" className="intro-section" aria-labelledby="scenarios-title">
          <div className="intro-section-heading">
            <p className="intro-eyebrow">从两种日常需求出发</p>
            <h2 id="scenarios-title">收集时轻一点，使用时有方向。</h2>
          </div>
          <div className="intro-scenarios">
            <article>
              <span className="intro-scene-number">01 / 找回积累</span>
              <h3>
                “我记得收藏过，
                <br />
                但不知道存在哪里。”
              </h3>
              <p>
                网页上的经验、手机里的截图、随手记下的文字，集中采集到 Grove。AI
                帮你提取要点、推荐项目与目录，确认后成为可检索的知识。
              </p>
              <div className="intro-scenario-question">
                <MessageSquare size={18} aria-hidden="true" />
                <div>
                  <small>使用场景示例 · 前端学习</small>
                  <p>“帮我找出之前收藏的、与 React 重复渲染有关的经验。”</p>
                </div>
              </div>
              <span className="intro-scene-outcome">
                <CheckCheck size={16} aria-hidden="true" /> 不必记住位置，让 Agent 帮你找回
              </span>
            </article>
            <article>
              <span className="intro-scene-number">02 / 建立框架</span>
              <h3>
                “想了解一个新领域，
                <br />
                却不知道从哪里开始。”
              </h3>
              <p>
                告诉 AI
                你的目标、已有基础和关注点，一起生成并调整目录草稿。确认合适的结构后，再围绕它有目标地收集资料、积累知识和学习。
              </p>
              <div className="intro-scenario-question">
                <FolderTree size={18} aria-hidden="true" />
                <div>
                  <small>使用场景示例 · 装修准备</small>
                  <p>“我对装修几乎不了解，先帮我梳理预算、流程和开工前准备。”</p>
                </div>
              </div>
              <span className="intro-scene-outcome">
                <CheckCheck size={16} aria-hidden="true" /> 从适合自己的结构开始，逐步积累
              </span>
            </article>
          </div>
        </section>

        <section id="capabilities" className="intro-section" aria-labelledby="capabilities-title">
          <div className="intro-section-heading">
            <p className="intro-eyebrow">三个 AI 核心能力</p>
            <h2 id="capabilities-title">从整理，到共创，再到协助使用。</h2>
            <p>让 AI 承担提取和查找，把判断与确认留给你。</p>
          </div>
          <div className="intro-capability-selector" role="group" aria-label="选择 AI 能力示例">
            {capabilities.map((item, index) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={selected === index}
                aria-controls="capability-example"
                onClick={() => setSelected(index)}
              >
                <item.icon size={18} aria-hidden="true" />
                {item.label}
                <ArrowRight size={15} aria-hidden="true" />
              </button>
            ))}
          </div>
          <div
            id="capability-example"
            className="intro-capability-board"
            role="region"
            aria-label={capability.label}
          >
            <div className="intro-board-heading">
              <div>
                <h3>{capability.title}</h3>
                <p>{capability.description}</p>
              </div>
              <span className="intro-example-badge">流程示意</span>
            </div>
            {selected === 0 ? (
              <RecommendationExample />
            ) : selected === 1 ? (
              <DirectoryExample />
            ) : (
              <AgentExample />
            )}
            <div className="intro-board-footnote">
              <ShieldCheck size={14} aria-hidden="true" /> 示例用于说明流程，不是真实用户数据或现场
              AI 运行结果。
            </div>
          </div>
        </section>

        <section id="devices" className="intro-section" aria-labelledby="devices-title">
          <div className="intro-section-heading">
            <p className="intro-eyebrow">三个端，同一份知识积累</p>
            <h2 id="devices-title">在顺手的地方收集，在需要的时候使用。</h2>
            <p>浏览时收集，随手记录，集中整理，需要时提问。</p>
          </div>
          <div className="intro-devices">
            <article>
              <div className="intro-device-symbol">
                <ScanLine size={30} strokeWidth={1.5} aria-hidden="true" />
              </div>
              <span className="intro-device-kind">浏览器扩展</span>
              <h3>看到就收。</h3>
              <p>框选网页内容，暂存多张截图，一次发送到 Grove 收集箱。</p>
              <ul>
                <li>网页框选截图</li>
                <li>单张发送与批量采集</li>
              </ul>
              <small>Chrome / Edge · 开发者模式加载</small>
            </article>
            <article>
              <div className="intro-device-symbol">
                <Smartphone size={30} strokeWidth={1.5} aria-hidden="true" />
              </div>
              <span className="intro-device-kind">原生移动 App</span>
              <h3>随手采集，随时问。</h3>
              <p>通过相机、相册和文字记录材料，用知识 Agent 查找和理解已有知识。</p>
              <ul>
                <li>相机 / 相册 / 文字采集</li>
                <li>知识对话与来源查看</li>
              </ul>
              <small>React Native + Expo · 开发体验阶段</small>
            </article>
            <article>
              <div className="intro-device-symbol">
                <Monitor size={30} strokeWidth={1.5} aria-hidden="true" />
              </div>
              <span className="intro-device-kind">桌面 Web</span>
              <h3>集中整理，持续积累。</h3>
              <p>审阅 AI 候选、共创目录，浏览、搜索和维护完整项目知识库。</p>
              <ul>
                <li>候选审阅与归属确认</li>
                <li>目录、知识浏览与检索</li>
              </ul>
              <small>桌面知识工作台 · 1024px 起支持</small>
            </article>
          </div>
        </section>

        <section
          id="engineering"
          className="intro-section intro-engineering"
          aria-labelledby="engineering-title"
        >
          <div className="intro-section-heading">
            <p className="intro-eyebrow">产品背后的设计与实现</p>
            <h2 id="engineering-title">让 AI 有帮助，也让知识有依据。</h2>
            <p>从数据模型到交互，保留人的决定权。</p>
          </div>
          <div className="intro-principles">
            <article>
              <ShieldCheck size={22} aria-hidden="true" />
              <div>
                <h3>AI 候选与正式知识分开</h3>
                <p>提取结果和目录建议先进入待确认状态，经用户确认后才应用到正式知识与目录。</p>
              </div>
            </article>
            <article>
              <BookOpen size={22} aria-hidden="true" />
              <div>
                <h3>正式知识保留原始来源</h3>
                <p>从知识条目回到材料核对；Agent 使用个人知识回答时，引用与回答依据清晰可见。</p>
              </div>
            </article>
            <article>
              <Layers size={22} aria-hidden="true" />
              <div>
                <h3>多端共用业务模型，数据按 Workspace 隔离</h3>
                <p>Web、原生 App 与扩展连接同一后端，围绕同一套项目、材料与知识模型协作。</p>
              </div>
            </article>
          </div>
          <div className="intro-tech-stack">
            <span>技术实现</span>
            <p>
              React + TypeScript <i>／</i> React Native + Expo <i>／</i> FastAPI + SQLAlchemy{' '}
              <i>／</i> PydanticAI
            </p>
          </div>
        </section>

        <section className="intro-closing" aria-label="开始使用">
          <Trees size={30} strokeWidth={1.5} aria-hidden="true" />
          <h2>
            从第一条材料开始，
            <br />
            积累自己的知识。
          </h2>
          <Button asChild size="lg">
            <a href="#login">
              {login ? '登录 Grove，开始整理' : '查看电脑端使用说明'}
              <ArrowRight aria-hidden="true" />
            </a>
          </Button>
        </section>
      </main>
      <footer className="intro-footer intro-container">
        <Brand />
        <p>AI 协助整理与共创，你掌握确认权。</p>
        <a href="#intro-main">
          回到顶部
          <ArrowRight size={14} aria-hidden="true" />
        </a>
      </footer>
    </div>
  )
}
