"""Evidence-first recognition. OCR hints alone never authorize live input."""
from pathlib import Path
import re

import cv2
import numpy as np

from .config import Profile
from .model import Observation, State, Token


def crop(image, box):
    h, w = image.shape[:2]
    x, y, bw, bh = box
    x1, y1 = max(0, int(x*w)), max(0, int(y*h))
    x2, y2 = min(w, int((x+bw)*w)), min(h, int((y+bh)*h))
    return image[y1:y2, x1:x2]


def parse_number(text: str, kind: str):
    text = text.replace('，', ',').replace(',', '').replace(' ', '').strip()
    if kind == 'placement':
        text=text.rstrip('!！。')
        # The Windows Chinese result banner spells ranks out (e.g. 第七名).
        chinese = re.fullmatch(r'第([一二三四五六七八])名', text)
        if chinese:
            return '一二三四五六七八'.index(chinese[1]) + 1
        match = re.fullmatch(r'(?:第)?([1-8])(?:名|st|nd|rd|th)?', text, re.I)
        return int(match[1]) if match else None
    if kind == 'gold':
        match = re.fullmatch(r'(\d{1,2})(?:/\d{1,2})?', text)
        return int(match[1]) if match and 0 <= int(match[1]) <= 30 else None
    if kind == 'rating':
        match = re.fullmatch(r'(?:当前)?(?:等级分|积分|评分|分数|rating)?[:：]?(\d{1,5})', text, re.I)
        return int(match[1]) if match and int(match[1]) <= 50000 else None
    if kind in ('upgrade_cost', 'tavern_tier'):
        match = re.fullmatch(r'\d{1,2}', text)
        high = 6 if kind == 'tavern_tier' else 30
        return int(text) if match and 0 <= int(text) <= high else None
    return None


def classify_hand_text(tokens,min_type_y=.68):
    text=''.join(t.text.replace(' ','') for t in tokens)
    spell=any(t.text.strip() in ('酒馆','酒館','法术','酒馆法术') and t.center[1]>min_type_y for t in tokens)
    if spell:
        if '附魔链索' in text or re.search(r'随机偷取酒[馆館]中的一[个個]随[从從]',text):return 'steal'
        if re.search(r'获得[一二三四五六七八九十\d]+(?:枚)?(?:铸币|金币)',text) and not re.search(r'消灭|移除|失去|伤害|随从',text):return 'coin'
        direct_buff=re.search(r'使一个(?:友方)?随从(?:获得|的)',text)
        tribe_buff=re.search(r'选择一个随从.*酒[馆館].*类型.*获得',text)
        if (direct_buff or tribe_buff) and not re.search(r'消灭|移除|敌方|失去|伤害',text):return 'buff'
        if '发现' in text or re.search(r'随机获取.*随从|获取一张.*随从牌',text):return 'discover'
        return 'unknown'
    if any(t.text.strip() in ('随从','野猪人','机械','野兽','恶魔','鱼人','海盗','龙','元素','纳迦','亡灵','畸变怪','全部') and t.center[1]>.68 for t in tokens):
        return 'minion'
    stats=[t for t in tokens if t.center[1]>.68 and re.fullmatch(r'\d{1,3}',t.text.strip())]
    if any(.08<abs(a.center[0]-b.center[0])<.20 and abs(a.center[1]-b.center[1])<.035 for a in stats for b in stats if a is not b):
        return 'minion'
    return 'unknown'


class Ocr:
    def __init__(self):
        from rapidocr import RapidOCR
        self.engine = RapidOCR(params={'Global.log_level':'error','EngineConfig.onnxruntime.intra_op_num_threads':2,
                                      'EngineConfig.onnxruntime.inter_op_num_threads':1})

    def tokens(self, image):
        if image.size == 0:
            return []
        result = self.engine(image,use_det=True,use_cls=True,use_rec=True)
        h, w = image.shape[:2]
        tokens = []
        if result.boxes is None or result.txts is None:
            return []
        for points, text, confidence in zip(result.boxes,result.txts,result.scores):
            pts = np.asarray(points)
            x, y = pts.min(axis=0)
            x2, y2 = pts.max(axis=0)
            tokens.append(Token(str(text), float(confidence), (float(x/w), float(y/h), float((x2-x)/w), float((y2-y)/h))))
        return tokens

    def recognize_line(self,image):
        if image.size==0:return []
        # A calibrated numeric ROI is already a text line. Detection can discard
        # a single placement digit, so recognize the line directly.
        result=self.engine(image,use_det=False,use_cls=False,use_rec=True)
        if result.txts is None:return []
        return [Token(str(text),float(score),(0,0,1,1)) for text,score in zip(result.txts,result.scores)]


class Vision:
    def __init__(self, profile: Profile, root: Path, ocr=None):
        self.profile = profile
        self.root = root
        self.ocr = ocr if ocr is not None else Ocr()
        self.cache = {}
        self.inspect_point=None
        self.inspect_source='hand'
        self.inspect_shop_spells=False

    def template(self, spec):
        relative = spec.get('file', '')
        path = (self.root / relative).resolve()
        # Profiles contain data, never executable paths outside the project.
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError('模板必须位于项目目录内')
        if path not in self.cache:
            content = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if content is None or content.std() < 5:
                raise ValueError(f'模板无效或接近纯色：{relative}')
            self.cache[path] = content
        return self.cache[path]

    def match(self, image, spec, region=None):
        if spec.get('alternatives'):
            primary={k:v for k,v in spec.items() if k!='alternatives'}
            return max(self.match(image,s,region) for s in [primary,*spec['alternatives']])
        template = self.template(spec)
        native_image=image
        frame_w = spec.get('frame_size', [image.shape[1], image.shape[0]])[0]
        # Normalize the capture to the calibration resolution. Upsampling a
        # small template instead loses text edges at Windows 125% scaling.
        if image.shape[1]!=frame_w:
            image=cv2.resize(image,(frame_w,round(image.shape[0]*frame_w/image.shape[1])),interpolation=cv2.INTER_AREA)
        width,height=template.shape[1],template.shape[0]
        if region is None:
            x, y, w, h = spec.get('box', [0, 0, 1, 1])
            region = [max(0,x-.04),max(0,y-.04),min(1,x+w+.04)-max(0,x-.04),min(1,y+h+.04)-max(0,y-.04)]
        target = crop(image, region)
        if target.shape[0] < height or target.shape[1] < width or not target.size:
            return 0.0
        if template.std() < 5 or target.std() < 2:
            return 0.0
        def score_patch(target,template):
            if target.shape[0]<template.shape[0] or target.shape[1]<template.shape[1] or template.std()<5:return 0.0
            scores=cv2.matchTemplate(target,template,cv2.TM_CCOEFF_NORMED)
            score=float(cv2.minMaxLoc(scores)[1])
            return score if np.isfinite(score) else 0.0
        score=score_patch(target,template)
        if native_image.shape[1]<frame_w:
            # Small text crops suffer rounding by one pixel at a lower resolution.
            # Compare both the original normalization and nearby integer template sizes.
            scale=native_image.shape[1]/frame_w
            target=crop(native_image,region)
            for dw in [-1,0,1]:
                for dh in [-1,0,1]:
                    sw,sh=round(width*scale)+dw,round(height*scale)+dh
                    if min(sw,sh)<8:continue
                    key=('resolution_template',spec['file'],sw,sh)
                    if key not in self.cache:self.cache[key]=cv2.resize(template,(sw,sh),interpolation=cv2.INTER_AREA)
                    score=max(score,score_patch(target,self.cache[key]))
        return score

    def marker(self, image, name, region):
        spec = self.profile.markers.get(name)
        return bool(spec and self.match(image, spec, region) >= spec.get('threshold', .90))

    def read_metric(self, image, kind, region_name=None):
        region_name=region_name or kind
        if region_name not in self.profile.verified_regions:
            return None
        roi = crop(image, self.profile.regions[region_name])
        if roi.size == 0:
            return None
        tokens=self.ocr.recognize_line(roi) if hasattr(self.ocr,'recognize_line') else self.ocr.tokens(roi)
        values = {parse_number(t.text, kind) for t in tokens if t.score >= .85}
        values.discard(None)
        if not values and kind=='gold' and hasattr(self.ocr,'recognize_line'):
            wide=cv2.resize(roi,None,fx=4,fy=2,interpolation=cv2.INTER_CUBIC)
            gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
            binary=cv2.threshold(gray,180,255,cv2.THRESH_BINARY)[1]
            binary=cv2.cvtColor(cv2.resize(binary,None,fx=3,fy=3),cv2.COLOR_GRAY2BGR)
            alternatives=[]
            for variant in (wide,binary):
                readings={parse_number(t.text,kind) for t in self.ocr.recognize_line(variant) if t.score>=.85}
                readings.discard(None)
                alternatives.append(readings.pop() if len(readings)==1 else None)
            if alternatives[0] is not None and alternatives[0]==alternatives[1]:
                return alternatives[0]
        return values.pop() if len(values) == 1 else None

    def inspect_context(self,obs,image):
        if self.inspect_point and obs.state in (State.RECRUIT,State.UNKNOWN):
            point=self.inspect_point
            lower=.14 if self.inspect_source=='shop' else .40
            tokens=[t for t in obs.tokens if t.score>=.85 and abs(t.center[0]-point[0])<.19 and lower<t.center[1]<1]
            labels=[t for t in tokens if t.text.strip() in ('酒馆','酒館','法术','酒馆法术','随从','野猪人','机械','野兽','恶魔','鱼人','海盗','龙','元素','纳迦','亡灵','畸变怪','全部')]
            if labels:
                label=max(labels,key=lambda t:t.box[3])
                tokens=[t for t in tokens if abs(t.center[0]-label.center[0])<.095]
            kind=classify_hand_text(tokens,.35 if self.inspect_source=='shop' else .68)
            if kind=='unknown' and self.inspect_source=='hand' and hasattr(self.ocr,'recognize_line'):
                # The enlarged hand card's footer can sit against the bottom
                # edge, where full-frame text detection confuses e.g. 随从.
                # Read only this local type line; both scales must agree.
                box=(max(0,point[0]-.042),.955,.10,.041)
                roi=crop(image,box)
                readings=[]
                for scale in (1,3):
                    local=self.ocr.recognize_line(cv2.resize(roi,None,fx=scale,fy=scale))
                    values={t.text.strip() for t in local if t.score>=.85}
                    readings.append(values.pop() if len(values)==1 else None)
                if readings[0] is not None and readings[0]==readings[1]:
                    tokens.append(Token(readings[0],.85,box))
                    kind=classify_hand_text(tokens)
                    if kind!='unknown':obs.metrics['hand_type_from_footer']=1
            obs.metrics['hand_card_kind']=kind
            obs.targets['inspected_hand']=tuple(point)

    def analyze(self, image, window_kind='game'):
        h, w = image.shape[:2]
        if window_kind=='game' and self.profile.layout_mode=='pc_v1' and abs(w/h/self.profile.aspect_ratio-1)<=.04:
            if w<960 or h<540:
                return Observation(State.UNKNOWN,evidence=f'客户区过小：{w}×{h}，至少需要 960×540 物理像素')
        # Hero availability and highlight are visual, not text-dependent.
        # Avoid full-screen OCR on every selection/confirmation observation.
        if window_kind=='game' and self.profile.layout_mode=='pc_v1' and abs(w/h/self.profile.aspect_ratio-1)<=.04:
            spec=self.profile.anchors.get('hero')
            if spec and self.match(image,spec)>=spec.get('threshold',.92):
                blocking=any(self.match(image,s)>=s.get('threshold',.92)
                             for name,s in self.profile.anchors.items() if name in ('notice','menu','confirm','choice'))
                if not blocking:
                    fast=Observation(State.HERO,self.match(image,spec),True,
                        targets={k:tuple(v) for k,v in self.profile.points.items() if k in self.profile.verified_points},
                        evidence='英雄模板、可选名牌与高亮快速识别')
                    from .pc_layout import apply_pc_layout
                    apply_pc_layout(self,image,fast)
                    if fast.available_heroes:return fast
        text_tokens = self.ocr.tokens(image)
        text = ' '.join(t.text for t in text_tokens if t.score >= .75)
        obs = Observation(State.UNKNOWN, tokens=text_tokens, evidence=text[:1500])
        # Launcher and game have independent aspect ratios.
        if window_kind != 'launcher' and abs(w/h / self.profile.aspect_ratio - 1) > .04:
            obs.evidence = f'宽高比不匹配：{w}×{h}；需要重新校准'
            return obs
        if re.search(r'验证码|输入密码|动态密码|Authenticator|enter.{0,5}password', text, re.I):
            obs.state, obs.confidence = State.AUTH, .99
            return obs
        for token in text_tokens:
            x,y=token.center
            if token.score>=.85 and re.fullmatch(r'开始战斗|战斗阶段|Combat',token.text,re.I) and (
                (.74<x<.86 and .40<y<.54) or (.40<x<.63 and .43<y<.57)):
                # The tavern portrait can remain behind the combat transition.
                # This OCR cue only suppresses inputs; it never authorizes one.
                obs.state,obs.confidence=State.COMBAT,token.score
                return obs
        matches = []
        choice_point=None
        for name, spec in self.profile.anchors.items():
            if (name == 'launcher') != (window_kind == 'launcher'):
                continue
            variants=[{k:v for k,v in spec.items() if k!='alternatives'},*spec.get('alternatives',[])]
            qualified=[]
            for variant in variants:
                score=self.match(image,variant)
                if score>=variant.get('threshold',.92):qualified.append((score,variant))
            if qualified:
                score,variant=max(qualified,key=lambda x:x[0])
                matches.append((score,State(name)))
                if name=='choice':choice_point=variant.get('click_point')
        matches.sort(reverse=True)
        # Modal overlays can leave an unchanged recruit header visible behind
        # them. A confirmed modal takes precedence over the underlying screen.
        for modal in (State.CONFIRM,State.MENU,State.NOTICE,State.CHOICE):
            selected=next((m for m in matches if m[1]==modal),None)
            if selected:
                matches=[selected]
                break
        if matches and (len(matches) == 1 or matches[0][0] - matches[1][0] >= .025):
            obs.confidence, obs.state = matches[0]
            obs.trusted = True
        elif not matches:
            # Hints are visible in observation mode, but cannot trigger actions.
            rules = [
                (State.RESULT, r'第[一二三四五六七八1-8]名|最终排名|Final Placement'),
                (State.HERO, r'选择.{0,3}英雄|Choose.{0,5}Hero'),
                (State.QUEUE, r'正在寻找|寻找对手|Finding Opponent'),
                (State.RECRUIT, r'招募阶段|Recruit Phase'),
                (State.COMBAT, r'开始战斗|战斗阶段|Combat Phase'),
                (State.LOBBY, r'酒馆战棋.*开始'),
            ]
            for state, pattern in rules:
                if re.search(pattern, text, re.I):
                    obs.state, obs.confidence = state, .6
                    break
        obs.targets = {k:tuple(v) for k,v in self.profile.points.items() if k in self.profile.verified_points}
        if window_kind=='launcher' and self.profile.layout_mode=='pc_v1' and 'launcher_play' in self.profile.verified_points:
            games=[t for t in text_tokens if t.score>=.90 and re.fullmatch(r'炉石传说|HEARTHSTONE',t.text.replace(' ',''),re.I)]
            play=[t for t in text_tokens if t.score>=.95 and re.fullmatch(r'进入游戏|开始游戏|PLAY',t.text.strip(),re.I)
                  and .02<t.center[0]<.40 and .55<t.center[1]<.98]
            if len(play)==1 and games:
                obs.state,obs.confidence,obs.trusted=State.LAUNCHER,min(play[0].score,max(t.score for t in games)),True
                obs.targets['launcher_play']=play[0].center
        if obs.state==State.CHOICE and choice_point and 'choice_1' in obs.targets:
            if len(choice_point)==2 and all(0<float(x)<1 for x in choice_point):
                obs.targets['choice_1']=tuple(choice_point)
        needed = {
            State.LOBBY: ['rating'], State.RESULT: ['placement','rating'],
            State.RECRUIT: ['gold','upgrade_cost','tavern_tier'],
        }.get(obs.state, [])
        obs.metrics = {name:self.read_metric(image,name,('rating_lobby' if obs.state==State.LOBBY else 'rating_result') if name=='rating' else name) for name in needed}
        self.inspect_context(obs,image)
        if self.profile.layout_mode == 'pc_v1' and obs.trusted:
            from .pc_layout import apply_pc_layout
            apply_pc_layout(self,image,obs)
            return obs
        if obs.state == State.HERO and obs.trusted:
            for slot in (2, 3):
                key = f'hero_{slot}_region'
                if key not in self.profile.verified_regions:
                    continue
                region = self.profile.regions[key]
                roi_tokens = self.ocr.tokens(crop(image, region))
                locked = any(re.search(r'锁定|解锁|通行证|locked|unlock|pass',t.text,re.I) for t in roi_tokens if t.score >= .75)
                locked |= self.marker(image,'hero_locked',region)
                if not locked and self.marker(image,'hero_available',region):
                    obs.available_heroes.append(slot)
                if not locked and self.marker(image,'hero_selected',region):
                    obs.metrics['hero_selected_slot'] = slot
        if obs.state == State.RECRUIT and obs.trusted:
            for group, count, result in [('shop',7,obs.shop_minions),('hand',10,obs.hand_minions)]:
                for i in range(1,count+1):
                    name = f'{group}_{i}'
                    key = f'{name}_region'
                    if name in obs.targets and key in self.profile.verified_regions:
                        if self.marker(image,'minion',self.profile.regions[key]):
                            result.append(name)
            counts = []
            for i in range(1,8):
                key = f'board_{i}_region'
                if key not in self.profile.verified_regions:
                    break
                region = self.profile.regions[key]
                occupied = self.marker(image,'board_minion',region)
                empty = self.marker(image,'board_empty',region)
                if occupied == empty:
                    break
                counts.append(int(occupied))
            if len(counts) == 7:
                obs.board_count = sum(counts)
        return obs
