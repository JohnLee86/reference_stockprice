# 기준주가 자동 보고서

매일 한국시간 17:30(영업일)에 KRX 데이터를 받아 기준주가를 계산하고,
A4 1장 보고서를 만들어 이메일로 발송하는 GitHub Actions 자동화입니다.

## 설정 방법
1. 이 폴더를 새 GitHub 저장소(비공개 추천)에 push
2. 저장소 Settings > Secrets and variables > Actions 에서 3개 Secret 등록
   - GMAIL_ADDRESS: 발신용 Gmail 주소
   - GMAIL_APP_PASSWORD: Gmail 앱 비밀번호 (일반 비밀번호 아님)
   - RECIPIENT_EMAIL: 받을 개인 이메일
3. config.json에서 대상 회사/종목코드 수정
4. Actions 탭에서 "일별 기준주가 보고서 자동 발송" 워크플로우를 수동 실행(Run workflow)해서 먼저 테스트
5. 문제없으면 매일 17:30에 자동 실행됨
