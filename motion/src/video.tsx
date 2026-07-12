import React from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

const C = {
  paper: '#F2F4F6',
  surface: '#FFFFFF',
  ink: '#1A2129',
  ink2: '#46525F',
  ink3: '#6B7885',
  line: '#D7DDE2',
  soft: '#E4E9ED',
  http: '#0F7FB3',
  httpSoft: '#D9EDF6',
  agent: '#A66312',
  agentSoft: '#F4E8D7',
  bad: '#B3372B',
  code: '#171D23',
};

const serif = 'Georgia, Charter, "Iowan Old Style", serif';
const sans = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
const mono = '"SFMono-Regular", Menlo, Consolas, monospace';

const clamp = (n: number) => Math.max(0, Math.min(1, n));
const ease = (f: number, a: number, b: number) =>
  interpolate(f, [a, b], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});

const Scene: React.FC<React.PropsWithChildren<{frame: number; start: number; end: number; dark?: boolean}>> = ({
  children,
  frame,
  start,
  end,
  dark = false,
}) => {
  const opacity = Math.min(ease(frame, start, start + 18), 1 - ease(frame, end - 18, end));
  return (
    <AbsoluteFill
      style={{
        background: dark ? C.code : C.paper,
        color: dark ? '#F2F5F7' : C.ink,
        opacity,
        overflow: 'hidden',
        fontFamily: serif,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

const Grid: React.FC<{dark?: boolean}> = ({dark}) => (
  <AbsoluteFill
    style={{
      opacity: dark ? 0.08 : 0.45,
      backgroundImage: `linear-gradient(${dark ? '#A9BAC6' : C.line} 1px, transparent 1px), linear-gradient(90deg, ${dark ? '#A9BAC6' : C.line} 1px, transparent 1px)`,
      backgroundSize: '64px 64px',
      maskImage: 'linear-gradient(to bottom, black, transparent 88%)',
    }}
  />
);

const Eyebrow: React.FC<React.PropsWithChildren<{color?: string}>> = ({children, color = C.ink3}) => (
  <div style={{fontFamily: mono, color, fontSize: 22, letterSpacing: '0.18em', textTransform: 'uppercase'}}>{children}</div>
);

const Pill: React.FC<React.PropsWithChildren<{kind?: 'http' | 'agent' | 'neutral'}>> = ({children, kind = 'neutral'}) => {
  const color = kind === 'http' ? C.http : kind === 'agent' ? C.agent : C.ink2;
  const bg = kind === 'http' ? C.httpSoft : kind === 'agent' ? C.agentSoft : C.paper;
  return <span style={{fontFamily: mono, fontSize: 19, color, background: bg, border: `1px solid ${color}`, borderRadius: 8, padding: '8px 14px'}}>{children}</span>;
};

const Logo: React.FC<{light?: boolean}> = ({light}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 18}}>
    <div style={{width: 48, height: 48, border: `2px solid ${light ? '#fff' : C.ink}`, borderRadius: 10, display: 'grid', placeItems: 'center', fontFamily: mono, fontSize: 22}}>H</div>
    <div style={{fontFamily: mono, fontWeight: 700, fontSize: 29, letterSpacing: '-0.04em'}}>API H</div>
  </div>
);

const BrowserCard: React.FC<{frame: number}> = ({frame}) => {
  const pulse = 0.5 + Math.sin(frame / 8) * 0.5;
  const rows = [0, 1, 2, 3];
  return (
    <div style={{width: 660, height: 500, background: C.surface, border: `1px solid ${C.line}`, borderRadius: 18, boxShadow: '0 28px 70px rgba(26,33,41,.12)', overflow: 'hidden'}}>
      <div style={{height: 64, borderBottom: `1px solid ${C.soft}`, display: 'flex', alignItems: 'center', gap: 10, padding: '0 22px'}}>
        {[C.bad, '#D4A12A', '#55A46B'].map((x) => <div key={x} style={{width: 13, height: 13, borderRadius: 20, background: x, opacity: 0.75}} />)}
        <div style={{marginLeft: 15, height: 34, flex: 1, borderRadius: 7, background: C.paper, fontFamily: mono, color: C.ink3, fontSize: 14, display: 'flex', alignItems: 'center', paddingLeft: 16}}>news.ycombinator.com</div>
      </div>
      <div style={{padding: '32px 38px'}}>
        <div style={{fontFamily: mono, fontSize: 13, color: C.ink3, letterSpacing: '.1em', marginBottom: 24}}>HACKER NEWS · TOP STORIES</div>
        {rows.map((r) => {
          const on = frame > 18 + r * 10;
          return (
            <div key={r} style={{display: 'grid', gridTemplateColumns: '34px 1fr 75px', gap: 14, padding: '16px 0', borderBottom: `1px solid ${C.soft}`, opacity: on ? 1 : .18, transform: `translateY(${on ? 0 : 8}px)`}}>
              <span style={{fontFamily: mono, color: C.ink3}}>{r + 1}</span>
              <div>
                <div style={{height: 12, background: r === 0 ? C.ink : C.ink2, width: `${82 - r * 8}%`, borderRadius: 6}} />
                <div style={{height: 8, background: C.soft, width: '44%', borderRadius: 6, marginTop: 12}} />
              </div>
              <span style={{fontFamily: mono, color: C.ink3, fontSize: 14}}>{[482, 316, 271, 198][r]} pts</span>
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', marginLeft: 555, marginTop: -124, transform: `scale(${1 + pulse * .08})`}}>
        <svg width="58" height="70" viewBox="0 0 58 70"><path d="M4 3L52 42L31 46L20 65L4 3Z" fill={C.ink} stroke="white" strokeWidth="4" strokeLinejoin="round" /></svg>
      </div>
    </div>
  );
};

const Intro: React.FC<{frame: number}> = ({frame}) => {
  const title = spring({frame, fps: 30, config: {damping: 18, stiffness: 85}});
  const sub = ease(frame, 22, 50);
  return (
    <Scene frame={frame} start={0} end={180}>
      <Grid />
      <div style={{position: 'absolute', left: 120, top: 78}}><Logo /></div>
      <div style={{position: 'absolute', left: 120, top: 270, width: 1540}}>
        <Eyebrow>Web workflows, compiled</Eyebrow>
        <h1 style={{fontSize: 112, lineHeight: .98, letterSpacing: '-0.055em', fontWeight: 500, margin: '34px 0 34px', transform: `translateY(${(1 - title) * 45}px)`, opacity: title}}>
          Browse once.<br/><span style={{color: C.http}}>Generate the route.</span>
        </h1>
        <div style={{fontFamily: sans, fontSize: 31, lineHeight: 1.45, color: C.ink2, width: 1040, opacity: sub, transform: `translateY(${(1 - sub) * 20}px)`}}>
          H Company Computer-Use helped create the built-in host maps. Live H can also propose simple routes that API H replays before activation.
        </div>
      </div>
      <div style={{position: 'absolute', right: 118, bottom: 76, fontFamily: mono, fontSize: 18, color: C.ink3}}>01 / PRODUCT FILM</div>
    </Scene>
  );
};

const Problem: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 150;
  const n = Math.min(4, Math.floor(clamp((local - 35) / 70) * 5));
  return (
    <Scene frame={frame} start={150} end={390}>
      <div style={{position: 'absolute', left: 100, top: 92, width: 660}}>
        <Eyebrow>The expensive loop</Eyebrow>
        <h2 style={{fontSize: 72, lineHeight: 1.05, fontWeight: 500, letterSpacing: '-.04em', margin: '28px 0'}}>Agents rediscover the same site. Every. Single. Run.</h2>
        <p style={{fontFamily: sans, color: C.ink2, fontSize: 28, lineHeight: 1.5}}>Full browse. Full cost. Full minutes. The answer changes—but the procedure usually doesn’t.</p>
        <div style={{marginTop: 44, display: 'flex', gap: 14, flexWrap: 'wrap'}}>
          <Pill kind="agent">1 H session</Pill><Pill kind="agent">38.2 s median</Pill><Pill kind="agent">$0.04 / run</Pill>
        </div>
      </div>
      <div style={{position: 'absolute', right: 100, top: 155}}><BrowserCard frame={local} /></div>
      {Array.from({length: n}).map((_, i) => (
        <div key={i} style={{position: 'absolute', right: 150 + i * 105, bottom: 82, width: 90, height: 90, borderRadius: 45, background: C.agentSoft, border: `2px solid ${C.agent}`, display: 'grid', placeItems: 'center', color: C.agent, fontFamily: mono, fontSize: 17}}>RUN<br/>0{i + 1}</div>
      ))}
      <svg style={{position: 'absolute', right: 175, bottom: 120}} width="530" height="160"><path d="M495 100 C350 10 180 8 15 88" fill="none" stroke={C.agent} strokeWidth="4" strokeDasharray="10 12"/><path d="M16 88l30-6-11 27z" fill={C.agent}/></svg>
    </Scene>
  );
};

const Compile: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 360;
  const nodes = [
    {x: 110, label: 'EXPLORE', sub: 'one H session', c: C.agent},
    {x: 735, label: 'GENERATE', sub: 'agent route map', c: '#F2F5F7'},
    {x: 1360, label: 'VERIFY', sub: 'replay + schema', c: C.http},
  ];
  const p1 = ease(local, 24, 78), p2 = ease(local, 92, 148);
  return (
    <Scene frame={frame} start={360} end={600} dark>
      <Grid dark />
      <div style={{position: 'absolute', left: 100, top: 74}}><Eyebrow color="#8FA0AD">The API H compiler</Eyebrow></div>
      <div style={{position: 'absolute', left: 100, top: 125, right: 100, display: 'flex', justifyContent: 'space-between', alignItems: 'end'}}>
        <h2 style={{fontSize: 76, lineHeight: 1.05, fontWeight: 500, letterSpacing: '-.04em', margin: 0}}>H helps map the route.</h2>
        <div style={{fontFamily: sans, fontSize: 26, color: '#A9B6C0', width: 580, lineHeight: 1.45}}>Built-ins ship as reviewed code. New simple plans activate only after one replay and schema validation.</div>
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: 500}}>
        <div style={{height: 4, background: '#313B44', margin: '0 230px'}} />
        <div style={{position: 'absolute', left: 325, top: 0, width: 540 * p1, height: 4, background: C.agent}} />
        <div style={{position: 'absolute', left: 950, top: 0, width: 540 * p2, height: 4, background: C.http}} />
        {nodes.map((node, i) => {
          const show = i === 0 ? ease(local, 0, 35) : i === 1 ? ease(local, 55, 95) : ease(local, 125, 165);
          return (
            <div key={node.label} style={{position: 'absolute', left: node.x, top: -112, width: 450, textAlign: 'center', opacity: show, transform: `translateY(${(1 - show) * 26}px)`}}>
              <div style={{margin: `0 auto ${i === 1 ? 24 : 36}px`, width: i === 1 ? 188 : 146, height: i === 1 ? 188 : 146, borderRadius: i === 1 ? 34 : 28, border: `${i === 1 ? 4 : 2}px solid ${node.c}`, background: i === 1 ? '#F4F6F7' : '#20272E', color: i === 1 ? C.ink : node.c, display: 'grid', placeItems: 'center', fontFamily: mono, fontSize: i === 1 ? 43 : 34, fontWeight: 700, transform: i === 1 ? 'translateY(-20px)' : undefined}}>{i === 0 ? '⌁' : i === 1 ? '{ }' : '→'}</div>
              <div style={{fontFamily: mono, fontSize: i === 1 ? 31 : 22, fontWeight: i === 1 ? 800 : 400, letterSpacing: '.14em', color: node.c, transform: i === 1 ? 'translateY(-20px)' : undefined}}>{node.label}</div>
              <div style={{fontFamily: sans, fontSize: 23, marginTop: 10, color: '#A9B6C0'}}>{node.sub}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', left: 365, bottom: 86, display: 'flex', gap: 355, color: '#758490', fontFamily: mono, fontSize: 18}}><span>site + goal</span><span>HTTP plan</span><span>versioned contract</span></div>
    </Scene>
  );
};

const Contract: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 570;
  const lines = [
    ['"version"', ': 2,', C.ink2],
    ['"status"', ': "active",', C.ink2],
    ['"method"', ': "hybrid",', C.http],
    ['"http"', ': { "mapper": "hn_firebase_v0" },', C.http],
    ['"created_with"', ': "h-company-computer-use",', C.http],
    ['"agent"', ': { "fallback": true },', C.agent],
    ['"health"', ': { "schema_gate": true }', '#7BA276'],
  ];
  return (
    <Scene frame={frame} start={570} end={780}>
      <div style={{position: 'absolute', left: 100, top: 78}}><Eyebrow>The durable artifact</Eyebrow></div>
      <div style={{position: 'absolute', left: 100, top: 150, width: 650}}>
        <h2 style={{fontSize: 72, lineHeight: 1.04, letterSpacing: '-.045em', fontWeight: 500, margin: 0}}>A contract is a procedure for inputs it has never seen.</h2>
        <p style={{fontFamily: sans, color: C.ink2, fontSize: 27, lineHeight: 1.5, marginTop: 35}}>Schemas, routing, validation and fallback—stored in SQLite, versioned, inspectable.</p>
      </div>
      <div style={{position: 'absolute', right: 70, top: 115, width: 1000, borderRadius: 22, background: C.code, boxShadow: '0 32px 80px rgba(26,33,41,.18)', overflow: 'hidden'}}>
        <div style={{height: 62, background: '#202830', display: 'flex', alignItems: 'center', padding: '0 26px', fontFamily: mono, color: '#83919D', fontSize: 16}}>contracts / hn-top-stories-v2.json</div>
        <div style={{padding: '38px 48px 42px', fontFamily: mono, fontSize: 29, lineHeight: 1.62, color: '#C7D3DC'}}>
          <div>{'{'}</div>
          {lines.map((l, i) => {
            const show = ease(local, 20 + i * 15, 46 + i * 15);
            return <div key={l[0]} style={{paddingLeft: 32, opacity: show, transform: `translateX(${(1 - show) * 20}px)`, color: l[2]}}><span style={{color: '#C7D3DC'}}>{l[0]}</span>{l[1]}</div>;
          })}
          <div>{'}'}</div>
        </div>
      </div>
      <div style={{position: 'absolute', left: 104, bottom: 86, display: 'flex', gap: 15}}><Pill>H-assisted map</Pill><Pill>reviewed mapper</Pill><Pill>agent fallback</Pill></div>
    </Scene>
  );
};

const Race: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 750;
  const http = ease(local, 38, 62);
  const agent = ease(local, 38, 205);
  return (
    <Scene frame={frame} start={750} end={960}>
      <div style={{position: 'absolute', left: 100, top: 78}}><Eyebrow>Same request. Two paths.</Eyebrow></div>
      <h2 style={{position: 'absolute', left: 100, top: 130, fontSize: 74, fontWeight: 500, letterSpacing: '-.045em', margin: 0}}>The gap between them is the product.</h2>
      <div style={{position: 'absolute', left: 100, right: 100, top: 305, border: `1px solid ${C.line}`, background: C.surface, borderRadius: 20, overflow: 'hidden'}}>
        <div style={{height: 72, borderBottom: `1px solid ${C.soft}`, padding: '0 30px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: mono, color: C.ink2, fontSize: 18}}><span>POST /v1/workflows/hn-top-stories/run</span><span>{'{ "limit": 5 }'}</span></div>
        {[
          {name: 'HTTP CONTRACT', p: http, c: C.http, result: '236 ms · $0.00 · 0 H sessions'},
          {name: 'AGENT BROWSE', p: agent, c: C.agent, result: '38.2 s · $0.04 · 1 H session'},
        ].map((r, i) => (
          <div key={r.name} style={{height: 180, borderBottom: i === 0 ? `1px solid ${C.soft}` : undefined, display: 'grid', gridTemplateColumns: '250px 1fr 410px', gap: 26, alignItems: 'center', padding: '0 30px'}}>
            <div style={{fontFamily: mono, fontSize: 19, color: r.c}}>{r.name}</div>
            <div style={{height: 20, background: C.soft, borderRadius: 10, overflow: 'hidden'}}><div style={{height: '100%', width: `${r.p * 100}%`, background: r.c, borderRadius: 10}} /></div>
            <div style={{fontFamily: mono, fontSize: 18, color: r.p >= .99 ? C.ink : C.ink3}}>{r.p >= .99 ? `200 OK · ${r.result}` : i === 0 ? `${Math.round(r.p * 236)} ms…` : `${(r.p * 38.2).toFixed(1)} s · browsing…`}</div>
          </div>
        ))}
      </div>
      {http >= .99 && <div style={{position: 'absolute', right: 100, bottom: 60, fontFamily: mono, fontSize: 22, color: C.http}}>~162× faster on this measured run</div>}
    </Scene>
  );
};

const Proof: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 930;
  const stats = [
    {v: '85/85', l: 'HTTP RUNS OK', c: C.http},
    {v: '96×', l: 'FASTER AT SCALE', c: C.http},
    {v: '$0', l: 'MARGINAL HTTP COST', c: C.http},
    {v: '0', l: 'BAD-DATA RESPONSES', c: '#5C8158'},
  ];
  return (
    <Scene frame={frame} start={930} end={1080} dark>
      <Grid dark />
      <div style={{position: 'absolute', left: 100, top: 75}}><Logo light /></div>
      <div style={{position: 'absolute', left: 100, top: 210}}>
        <Eyebrow color="#8FA0AD">19-site live evaluation · 100 recorded runs</Eyebrow>
        <h2 style={{fontSize: 82, fontWeight: 500, letterSpacing: '-.045em', margin: '25px 0 0'}}>Measured, not projected.</h2>
      </div>
      <div style={{position: 'absolute', left: 100, right: 100, top: 465, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 22}}>
        {stats.map((s, i) => {
          const show = ease(local, 12 + i * 9, 42 + i * 9);
          return (
            <div key={s.l} style={{height: 235, border: '1px solid #36414B', borderRadius: 18, background: '#20272E', padding: '32px 34px', opacity: show, transform: `translateY(${(1 - show) * 35}px)`}}>
              <div style={{fontFamily: mono, color: s.c, fontSize: 64, fontWeight: 700, letterSpacing: '-.06em'}}>{s.v}</div>
              <div style={{fontFamily: mono, color: '#A5B2BC', fontSize: 17, letterSpacing: '.12em', marginTop: 35}}>{s.l}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', left: 100, right: 100, bottom: 92, display: 'flex', alignItems: 'end', justifyContent: 'space-between'}}>
        <div style={{fontFamily: serif, fontSize: 37, fontStyle: 'italic', color: '#E1E7EB'}}>“Cache stores answers. A contract stores how to answer.”</div>
        <div style={{textAlign: 'right'}}><div style={{fontFamily: mono, fontSize: 24, color: '#fff'}}>github.com/gurul/apiH</div><div style={{fontFamily: sans, fontSize: 18, color: '#8796A2', marginTop: 10}}>FastAPI · SQLite · H Computer-Use</div></div>
      </div>
    </Scene>
  );
};

export const APIHFilm: React.FC = () => {
  const frame = useCurrentFrame();
  useVideoConfig();
  return (
    <AbsoluteFill style={{background: C.paper}}>
      <Sequence from={0} durationInFrames={180}><Intro frame={frame} /></Sequence>
      <Sequence from={150} durationInFrames={240}><Problem frame={frame} /></Sequence>
      <Sequence from={360} durationInFrames={240}><Compile frame={frame} /></Sequence>
      <Sequence from={570} durationInFrames={210}><Contract frame={frame} /></Sequence>
      <Sequence from={750} durationInFrames={210}><Race frame={frame} /></Sequence>
      <Sequence from={930} durationInFrames={150}><Proof frame={frame} /></Sequence>
    </AbsoluteFill>
  );
};

export const APIHStill: React.FC = () => (
  <AbsoluteFill style={{background: C.paper, color: C.ink, fontFamily: serif, overflow: 'hidden'}}>
    <Grid />
    <div style={{position: 'absolute', left: 120, top: 78}}><Logo /></div>
    <div style={{position: 'absolute', left: 120, top: 270}}>
      <Eyebrow>Web workflows, compiled</Eyebrow>
      <h1 style={{fontSize: 112, lineHeight: .98, letterSpacing: '-0.055em', fontWeight: 500, margin: '34px 0'}}>Browse once.<br/><span style={{color: C.http}}>Generate the route.</span></h1>
      <div style={{fontFamily: sans, fontSize: 31, color: C.ink2}}>H-assisted host maps · optional live route proposals · verified REST execution.</div>
    </div>
    <div style={{position: 'absolute', right: 120, bottom: 90, display: 'flex', gap: 14}}><Pill kind="http">236 ms</Pill><Pill kind="agent">38.2 s</Pill></div>
  </AbsoluteFill>
);
