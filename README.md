# 프로젝트 시작 방법

## 1. 레포지토리 클론

본 프로젝트는 Git Submodule을 사용합니다.
아래 명령어로 메인 레포와 서브모듈을 함께 클론해주세요.

```git clone --recursive -b develop https://github.com/Greenora/project-gachimura-main-deployment.git
cd project-gachimura-main-deployment
```

---

## 2. 개발 환경 실행

1) Docker (전체 실행)

2) ``` docker compose up ```

	•	배포 환경 기준 실행
	•	DB / Backend / Frontend 포함

---

## 3. 로컬 개발 시
1) Backend 
  - 도커 내 백엔드 컨테이너 종료 후 로컬 서버 on

  ``` npm run start:dev ```

2) Frontend
  - 도커 내 프론트엔드 컨테이너 종료 후 로컬 서버 on
    
  ``` npm run dev ```

빠른 개발과 디버깅을 위해 기본 세팅으로 로컬 실행을 권장합니다.

---

 ## 4. 브랜치 전략
	-	프론트 / 백엔드:
	  -	 기능 브랜치 → main 브랜치로 PR
	  -	 서브모듈 관리 및 통합은 관리자가 진행

--- 

## 5. 구조를 이렇게 구성한 이유
	•	프론트/백엔드 독립 개발을 위함
	•	Docker로 배포 환경과 동일한 구성 유지
	•	팀원은 복잡한 설정 없이 개발에만 집중

--- 

## 6. 전체 레포지터리 구조 
```
main-development (통합 레포)
 ├─ main   : 배포 환경
 └─ develop: 기능 통합 브랜치

frontend-development
 └─ main → main-development:develop 에 자동 반영

backend-development
 └─ main → main-development:develop 에 자동 반영
```
