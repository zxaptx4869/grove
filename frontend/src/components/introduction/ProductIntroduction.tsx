import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowDown,
  ArrowRight,
  BookOpen,
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
    description: '从截图与文字中提取要点，推荐项目和目录，经你确认后成为正式知识。',
  },
  {
    id: 'structure',
    icon: FolderTree,
    label: 'AI 目录共创',
    description: '根据你的目标与基础生成目录草稿，继续对话调整，确认适合自己的结构。',
  },
  {
    id: 'agent',
    icon: MessageSquare,
    label: '知识 Agent 协助',
    description: '查找已有知识、解释内容、继续追问，保留引用供你核对。',
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
          <FileText size={15} aria-hidden="true" /> 原始材料
        </span>
        <h3>关于 React 重复渲染的笔记</h3>
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
        <h3>优化前，先定位渲染开销</h3>
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
          </li>
          <li>
            02 <span>流程与协作</span>
          </li>
          <li>
            03 <span>开工前检查</span>
          </li>
        </ul>
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
          <Sparkles size={15} aria-hidden="true" /> Grove · 回答示例
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
            <span>来源材料：React 学习笔记</span>
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
            <a href="#engineering">设计原则</a>
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
              采集截图与文字，让 AI 提取要点、推荐项目与目录。 与 AI 共创学习框架，再通过知识 Agent
              查找和使用积累的内容。
            </p>
            <Button asChild size="lg" className="intro-hero-action">
              <a href="#scenarios">
                了解功能
                <ArrowDown aria-hidden="true" />
              </a>
            </Button>
          </div>
          <aside
            id="login"
            className={login ? 'intro-login-card' : 'intro-mobile-notice'}
            aria-label={login ? '登录工作台' : '电脑端使用提示'}
          >
            {login ? (
              <>{login}</>
            ) : (
              <>
                <Monitor size={22} aria-hidden="true" />
                <div>
                  <strong>在电脑端登录，开始整理</strong>
                </div>
              </>
            )}
          </aside>
        </section>

        <section id="scenarios" className="intro-section" aria-labelledby="scenarios-title">
          <div className="intro-section-heading">
            <h2 id="scenarios-title">两种方式，积累自己的知识。</h2>
          </div>
          <div className="intro-scenarios">
            <article>
              <h3>
                “我记得收藏过，
                <br />
                但不知道存在哪里。”
              </h3>
              <p>
                把零散截图与文字集中到 Grove，AI 提取要点并推荐归属。 确认后，需要时让 Agent
                帮你找回。
              </p>
            </article>
            <article>
              <h3>
                “想了解一个新领域，
                <br />
                却不知道从哪里开始。”
              </h3>
              <p>和 AI 一起搭建适合自己的目录，确认框架后， 再围绕它有目标地收集资料和学习。</p>
            </article>
          </div>
        </section>

        <section id="capabilities" className="intro-section" aria-labelledby="capabilities-title">
          <div className="intro-section-heading">
            <h2 id="capabilities-title">AI 帮你整理、共创和查找。</h2>
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
                <p>{capability.description}</p>
              </div>
              <span className="intro-example-badge">示例</span>
            </div>
            {selected === 0 ? (
              <RecommendationExample />
            ) : selected === 1 ? (
              <DirectoryExample />
            ) : (
              <AgentExample />
            )}
          </div>
        </section>

        <section id="devices" className="intro-section" aria-labelledby="devices-title">
          <div className="intro-section-heading">
            <h2 id="devices-title">三个端，连接同一份知识。</h2>
          </div>
          <div className="intro-devices">
            <article>
              <div className="intro-device-symbol">
                <ScanLine size={30} strokeWidth={1.5} aria-hidden="true" />
              </div>
              <h3>浏览器扩展</h3>
              <p>浏览网页时框选截图，单张或批量发送到收集箱。</p>
              <small>Chrome / Edge · 本地加载</small>
            </article>
            <article>
              <div className="intro-device-symbol">
                <Smartphone size={30} strokeWidth={1.5} aria-hidden="true" />
              </div>
              <h3>移动 App</h3>
              <p>随手拍照、选图或记录文字，也能通过 Agent 查找和理解知识。</p>
              <small>开发体验阶段</small>
            </article>
            <article>
              <div className="intro-device-symbol">
                <Monitor size={30} strokeWidth={1.5} aria-hidden="true" />
              </div>
              <h3>桌面 Web</h3>
              <p>集中审阅 AI 候选、共创目录，浏览、搜索和维护项目知识。</p>
            </article>
          </div>
        </section>

        <section
          id="engineering"
          className="intro-section intro-engineering"
          aria-labelledby="engineering-title"
        >
          <div className="intro-section-heading">
            <h2 id="engineering-title">AI 协助，你来决定。</h2>
          </div>
          <div className="intro-principles">
            <article>
              <ShieldCheck size={22} aria-hidden="true" />
              <div>
                <h3>确认后才成为正式知识</h3>
                <p>AI 提取与目录建议先作为草稿，由你确认、修改或拒绝。</p>
              </div>
            </article>
            <article>
              <BookOpen size={22} aria-hidden="true" />
              <div>
                <h3>每条知识都能核对来源</h3>
                <p>保留原始材料，Agent 使用个人知识回答时提供引用。</p>
              </div>
            </article>
            <article>
              <Layers size={22} aria-hidden="true" />
              <div>
                <h3>多端协作，数据隔离</h3>
                <p>三个端共用后端与知识模型，数据按工作空间隔离。</p>
              </div>
            </article>
          </div>
        </section>
      </main>
      <footer className="intro-footer intro-container">
        <Brand />
        <a href="#intro-main">
          回到顶部
          <ArrowRight size={14} aria-hidden="true" />
        </a>
      </footer>
    </div>
  )
}
