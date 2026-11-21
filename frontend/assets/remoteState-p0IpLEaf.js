function a(t,n){const{data:r,error:e,loading:o}=t;return r==null?e?"error":o?"loading":"empty":e?"stale":n?.(r)?"empty":"ready"}export{a as r};
