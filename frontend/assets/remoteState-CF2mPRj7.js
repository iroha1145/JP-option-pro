function a(t,r){const{data:e,error:n,loading:o}=t;return e==null?n?"error":o?"loading":"empty":n?"stale":r!=null&&r(e)?"empty":"ready"}export{a as r};
