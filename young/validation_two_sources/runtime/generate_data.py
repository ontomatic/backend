from __future__ import annotations

import json
import math
import random
import re
from collections import OrderedDict
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

ROOT=Path(__file__).parent
CATALOG=json.loads((ROOT/'catalog.json').read_text())
SKILL=(ROOT.parents[1]/'references/qc_contract.md').read_text()

def parse_schemas():
    schemas=OrderedDict()
    pat=re.compile(r'### 2-(\d+)\. ([^\n]+)\n```\n(.*?)\n```',re.S)
    for m in pat.finditer(SKILL):
        n=int(m.group(1))
        if n>10:continue
        name=m.group(2).split(' (')[0].strip()
        fields=[x.strip() for x in m.group(3).replace('\n',' ').split(',') if x.strip()]
        schemas[name]=fields
    assert len(schemas)==10,list(schemas)
    return schemas

SCHEMAS=parse_schemas()
NAMES=list(SCHEMAS)

def new(name,values):
    r=OrderedDict((h,'') for h in SCHEMAS[name])
    r.update({'스키마버전':'1.0','origin':'synthetic'})
    assert set(values)<=set(r),(name,set(values)-set(r))
    r.update(values)
    return r

ISSUES=['영상 출력 지연','전원 재기동 편차','외관 표면 손상','저조도 영상 잡음','하우징 체결 흔들림','포장 라벨 오기','초점 조정 편차','운용 온도 확인 지연']
PROCESSES=['조립','영상 검사','외관 검사','출하 검사','포장','수입 검사','기능 시험','최종 승인']

def make_model(cat):
    model=cat['model'];num=cat['sample_no'];rng=random.Random(20261027+int(num))
    data=OrderedDict((n,[]) for n in NAMES);defects=[]
    items=cat['items'];itemmap={x['name']:x for x in items}
    def log(sheet,row,kind,explanation):
        defects.append({'시트':sheet,'행ID':row['행ID'],'결함유형':kind,'설명':explanation})
    def lot(i):return f'SYN-{model}-2610-{i:03d}'
    def issue(i):return f'{ISSUES[(i-1)%len(ISSUES)]} 사례 {num}-{i:02d}: LOT {lot((i-1)%7+1)} 검사 중 재확인 필요'
    def source_note(item):
        if item['name']=='외관':return '외관 기준은 합성·업계 관행, 데이터시트 근거 없음'
        return f"기준치 출처: {model} 데이터시트 {item['section']} {item['page']}쪽; 운영정보는 합성"

    # 1. Each LOT includes every verified characteristic available for this model.
    name=NAMES[0]
    for l in range(1,8):
        day=(date(2026,10,1)+timedelta(days=l)).isoformat()
        for j,item in enumerate(items,1):
            spec=item['value'];category='외관검사' if item['name'] in ('외관','색상','재질','제품사이즈','제품무게') else '동작검사' if item['name'] in ('전원','동작온도','습도','소비전력','방수내충격등급') else '성능검사'
            row=new(name,{'성적서번호':f'SYN-FQC-{num}-{l:03d}','검사유형':'완제품 출하검사','발행주체유형':'한화비전','발행주체명':'한화비전','검사일자':day,'생산일자':(date.fromisoformat(day)-timedelta(days=1)).isoformat(),'모델코드':model,'품명':f'{model} 카메라','LOT No.':lot(l),'PO No.':f'SYN-PO-{num}-{l:03d}','시작일련번호':f'SYN{num}{l:03d}0001','종료일련번호':f'SYN{num}{l:03d}0100','총수량':100,'검사수량':13,'단위':'EA','분류':category,'검사항목':item['name'],'기준치':spec,'결과':'OK','측정값':spec,'LQC검사자':'가상검사자 김A','OQC검사자':'가상검사자 박B','불량수량':0,'불량내용':'해당 없음','처리방향':'출하 승인','승인자':'가상승인자 이C','비고':source_note(item),'행ID':f'FQC-{num}-{l:03d}-{j:02d}'})
            if l==1 and j==1:
                row['LQC검사자']='';log(name,row,'필수공란','LQC검사자 누락')
            if l==2 and item['name']=='동작온도':
                old=row['측정값'];row['측정값']=old.replace('°C',' 도');assert row['측정값']!=old
                log(name,row,'단위표기차이','동작온도 측정값 단위 표기 변형')
            if l==4 and item['name']=='전원':
                row.update({'결과':'NG','측정값':'전원 인가 실패','불량수량':1,'불량내용':f'{model} 전원 재기동 실패 1건','처리방향':''})
                log(name,row,'결과-처리방향 불일치','NG인데 처리방향 누락')
            if l==5 and item['name']=='동작온도':
                row['검사항목']='동작 온도';log(name,row,'사양명 별칭표기','동작온도 사양명 공백 변형')
            if l==6 and j==2:
                row['결과']='합격';log(name,row,'판정값 도메인이탈','OK/NG 외 결과값')
            if l==7 and item['name']=='동작온도':
                old=row['기준치'];row['기준치']=old.replace('°C','');assert '~' in old and row['기준치']!=old
                log(name,row,'범위표기차이','범위 기준치의 °C 단위 생략')
            data[name].append(row)
            if l==3 and j==2:
                data[name].append(deepcopy(row));log(name,row,'중복행','성적서번호·LOT·검사항목·측정값 및 행ID 완전 중복')

    name=NAMES[1]
    for i in range(1,9):
        row=new(name,{'NCR번호':f'SYN-NCR-{num}-{i:03d}','발행일':f'2026-10-{10+i:02d}','모델코드':model,'품명':f'{model} 카메라','LOT No.':lot((i-1)%7+1),'발견공정':PROCESSES[i-1],'부적합내용':issue(i),'부적합수량':1+(i%3),'격리여부':'예','처리판정':'재작업','근본원인':f'{i}차 분석: 가상 접점·조립 편차 확인','시정조치':f'{i}차 재조립과 기능 재검사','유효성검증':f'{i}차 표본 재검사 적합','승인자':'가상승인자 이C','종결일':f'2026-10-{13+i:02d}','비고':'합성 NCR 기록','행ID':f'NCR-{num}-{i:03d}'})
        if i==2:row.update({'처리판정':'폐기','근본원인':'','시정조치':'','유효성검증':''});log(name,row,'후속조치 공란','폐기 판정 뒤 원인·시정·검증 누락')
        if i==4:row['종결일']='';log(name,row,'종결일 공란','종결일 누락')
        if i==6:row['격리여부']='';log(name,row,'격리여부 공란','격리 여부 누락')
        data[name].append(row)

    name=NAMES[2]
    plan_items=[x for x in items if x['name']!='외관']
    for i in range(1,9):
        it=plan_items[(i-1)%len(plan_items)]
        row=new(name,{'계획서번호':f'SYN-CP-{num}-{i:03d}','모델코드':model,'공정명':PROCESSES[i-1],'설비·치공구':f'가상 검사지그 {i}','관리특성(사양)':it['name'],'규격·공차':it['value'],'측정방법':'사양 비교 및 기록','표본크기':'13 EA','검사주기':'LOT별','관리방법':'검사 이력 보관','이상 시 대응계획':'격리 후 재검사','비고':source_note(it),'행ID':f'CP-{num}-{i:03d}'})
        if i==2:
            for f in ['규격·공차','측정방법','표본크기','검사주기','관리방법']:row[f]=''
            log(name,row,'관리계획 핵심공란','규격·측정·표본·주기·관리방법 누락')
        if i==5:row['이상 시 대응계획']='';log(name,row,'대응계획 공란','이상 시 대응계획 누락')
        data[name].append(row)

    name=NAMES[3]
    for i in range(1,9):
        it=items[(i-1)%len(items)]
        row=new(name,{'체크리스트번호':f'SYN-CHK-{num}-{i:03d}','검사유형':'출하검사','모델코드':model,'LOT No.':lot((i-1)%7+1),'검사단위':'LOT','전수/발췌':'발췌','AQL':'1.0','검사항목':it['name'],'판정기준':it['value'],'확인결과':'합격','처리방법':'출하 승인','검사자':'가상검사자 박B','비고':'합성 체크리스트','행ID':f'CHK-{num}-{i:03d}'})
        if i==2:row.update({'확인결과':'불합격','처리방법':''});log(name,row,'불합격 조치공란','불합격인데 처리방법 누락')
        if i==5:row['AQL']='';log(name,row,'AQL 누락','발췌 검사 AQL 누락')
        data[name].append(row)

    name=NAMES[4]
    for i in range(1,9):
        vals=[round(4.0+rng.uniform(-.04,.04),3) for _ in range(5)]
        if i==3:vals=[4.27,4.28,4.29,4.31,4.32]
        avg=round(sum(vals)/5,3);span=round(max(vals)-min(vals),3)
        row=new(name,{'관리도번호':f'SYN-SPC-{num}-001','모델코드':model,'특성명':'가상 조립 정렬 간격(mm)','부분군번호':i,'측정값1':vals[0],'측정값2':vals[1],'측정값3':vals[2],'측정값4':vals[3],'측정값5':vals[4],'평균(X̄)':avg,'범위(R)':span,'CL':4.0,'UCL':4.15,'LCL':3.85,'이상원인·조치':'정상 범위' if i!=3 else '','행ID':f'SPC-{num}-{i:03d}'})
        if i==3:log(name,row,'관리한계 초과 후속공란','평균이 UCL 초과, 이상원인·조치 누락')
        if i==5:row['특성명']='';log(name,row,'관리특성 공란','측정값은 있으나 특성명 누락')
        data[name].append(row)

    name=NAMES[5]
    for i in range(1,9):
        score=91-i*2
        row=new(name,{'평가번호':f'SYN-SUP-{num}-{i:03d}','협력사명':f'가상부품사 {num}-{i}','평가일':f'2026-10-{10+i:02d}','품질관리상태':'양호','수리실태':'적정','제품품질':'양호','현장안전·신뢰도':'적정','계약이행':'기한 준수','평점(100점)':score,'등급':'A' if score>=90 else 'B' if score>=80 else 'C','평가자':'가상평가자 최D','비고':'실제 공급사·평가 아님','행ID':f'SUP-{num}-{i:03d}'})
        if i==2:row['등급']='';log(name,row,'등급 공란','평점이 있으나 등급 누락')
        if i==5:row['평가자']='';log(name,row,'평가자 공란','평가자 누락')
        data[name].append(row)

    name=NAMES[6]
    for i in range(1,9):
        row=new(name,{'접수번호':f'SYN-CLM-{num}-{i:03d}','접수일':f'2026-10-{10+i:02d}','고객사':f'가상고객사 {num}-{i}','모델코드':model,'품명':f'{model} 카메라','LOT No.':lot((i-1)%7+1),'사고개요':issue(i).replace('검사 중','현장 운용 중'),'원인분석':f'{i}차 가상 분석: 시험 조건 확인','처리결과':f'{i}차 고객 안내 및 대체품 발송','처리일':f'2026-10-{14+i:02d}','담당자':'가상담당자 정E','비고':'실제 고객·사고 아님','행ID':f'CLM-{num}-{i:03d}'})
        if i==2:row.update({'원인분석':'','처리결과':'','처리일':''});log(name,row,'미해결 방치','접수 후 원인·결과·처리일 모두 공란')
        if i==5:row['담당자']='';log(name,row,'담당자 공란','담당자 누락')
        data[name].append(row)

    name=NAMES[7]
    for i in range(1,9):
        row=new(name,{'회의록번호':f'SYN-MTG-{num}-{i:03d}','회차':i,'일자':f'2026-10-{10+i:02d}','안건':f'{model} {ISSUES[i-1]} 검토','장소':'가상 품질회의실','시간':'10:00~11:00','진행자':'가상진행자 이C','기록자':'가상기록자 문F','불참자·사유':'없음','회의내용':f'{i}차 회의에서 {ISSUES[i-1]} 시험 조건과 대응 일정을 검토함','건의사항':f'{i}차 결과 공유 요청','결재':'가상결재 완료','행ID':f'MTG-{num}-{i:03d}'})
        if i==2:row.update({'시간':'','기록자':'','결재':''});log(name,row,'회의 필수정보 공란','시간·기록자·결재 누락')
        if i==5:row['진행자']='';log(name,row,'진행자 공란','진행자 누락')
        data[name].append(row)

    name=NAMES[8]
    for i in range(1,9):
        row=new(name,{'일지번호':f'SYN-LOG-{num}-{i:03d}','일자':f'2026-10-{10+i:02d}','공정명':PROCESSES[i-1],'모델코드':model,'LOT No.':lot((i-1)%7+1),'작업자':'가상작업자 오G','품질 체크포인트':f'{i}차 {ISSUES[i-1]} 확인','확인결과':'정상','수정조치내용':'해당 없음','합격수':100,'불합격수':0,'비고':'합성 작업 기록','행ID':f'LOG-{num}-{i:03d}'})
        if i==2:row.update({'확인결과':'이상있음','수정조치내용':'','합격수':99,'불합격수':1});log(name,row,'이상 후속조치 공란','이상있음인데 수정조치내용 누락')
        if i==5:row['작업자']='';log(name,row,'작업자 공란','작업자 누락')
        data[name].append(row)

    name=NAMES[9]
    parts=[('SYN-LENS','렌즈','외관','흠집·변형 없음'),('SYN-SENSOR','이미지센서','전기적 확인','입고검사 기준 확인'),('SYN-HOUSING','하우징','외관','변형 없음')]
    for l in range(1,5):
        for j,(code,part,item,criterion) in enumerate(parts,1):
            row=new(name,{'성적서번호':f'SYN-IQC-{num}-{l:03d}','검사유형':'수입검사','입고일자':f'2026-10-{l+1:02d}','공급사':f'가상부품사 {j}','부품코드':f'{code}-{num}-001','부품명':part,'적용모델':model,'입고LOT':f'SYN-IN-{num}-{l:03d}','입고수량':200,'샘플수량':13,'검사항목':item,'기준치':criterion,'결과':'OK','측정값':criterion,'합부판정':'합격','검사자':'가상검사자 김A','승인자':'가상승인자 이C','비고':'상식적 BOM 분해, 실물 BOM 미확인; 전 항목 합성','행ID':f'IQC-{num}-{l:03d}-{j:02d}'})
            if l==1 and j==1:row['부품코드']=row['부품코드'].replace('-','');log(name,row,'부품코드오기재','부품코드 하이픈 누락')
            if l==2 and j==2:row['샘플수량']=12;log(name,row,'샘플수량불일치','LOT 표본 기준 13 EA와 불일치')
            if l==3 and j==3:row.update({'결과':'NG','합부판정':'합격'});log(name,row,'판정-조치불일치','NG인데 합격 판정')
            data[name].append(row)
            if l==4 and j==1:data[name].append(deepcopy(row));log(name,row,'중복행','IQC 행 전체 중복')
    return {'sample_no':num,'model':model,'source_url':cat['source_url'],'source_id':cat['source_id'],'data':data,'defects':defects,'catalog_items':items,'omissions':cat['omissions']}

def validate(pack):
    for name,rows in pack['data'].items():
        assert rows
        for row in rows:
            assert list(row)==SCHEMAS[name],(name,list(row),SCHEMAS[name])
            assert row['origin']=='synthetic'
    assert len(pack['data'][NAMES[0]])==7*len(pack['catalog_items'])+1
    assert len(pack['data'][NAMES[9]])==13
    assert len(pack['defects'])==7+3+2+2+2+2+2+2+2+4,len(pack['defects'])
    for d in pack['defects']:
        assert any(r['행ID']==d['행ID'] for r in pack['data'][d['시트']])
    for r in pack['data'][NAMES[4]]:
        vals=[r[f'측정값{i}'] for i in range(1,6)]
        assert math.isclose(r['평균(X̄)'],round(sum(vals)/5,3))
        assert math.isclose(r['범위(R)'],round(max(vals)-min(vals),3))

def main():
    packs=[]
    for cat in CATALOG:
        pack=make_model(cat);validate(pack);packs.append(pack)
    (ROOT/'schema.json').write_text(json.dumps(SCHEMAS,ensure_ascii=False,indent=2))
    (ROOT/'data.json').write_text(json.dumps(packs,ensure_ascii=False,indent=2))
    print('models',len(packs),'rows',sum(sum(len(v) for v in p['data'].values()) for p in packs),'defects',sum(len(p['defects']) for p in packs))

if __name__=='__main__':main()
