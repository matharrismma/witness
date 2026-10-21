import math
par = math.ceil(12_000_000/0.98/5000)*5000
r=0.045/12; io=par*r; n=216
pi=par*r*(1+r)**n/((1+r)**n-1)
ti=24*io+216*pi-par
dscr=1_500_000/(12*pi)
ev=[max(9_000_000*(1-0.1*y),1_800_000) for y in range(1,11)]
mill=[27.9]*5+[28.5]*5
full=[(18_000_000+ev[i])*0.40*mill[i]/1000 for i in range(10)]
ab=[1.0-0.1*i for i in range(10)]
abated=[full[i]*ab[i] for i in range(10)]
pilot=[full[i]-abated[i] for i in range(10)]
npv=sum(abated[i]/1.05**(i+1) for i in range(10))
T=dict(par=par,monthly_io=io,monthly_pi=pi,total_interest=ti,dscr_amort=dscr,equip_val_y3=ev[2],
 full_tax_y1=full[0],full_tax_y8=full[7],pilot_y6=pilot[5],total_abated_10=sum(abated),npv_abated=npv,
 abated_per_job=sum(abated)/150)
if __name__=="__main__":
    for k,v in T.items(): print(f"{k:16s} {v:,.2f}")
