#include "demo_candidate.h"
#include <math.h>
#include <stddef.h>
int pl_demo_candidate(const double p[3], pl_demo_candidate_t *out) {
    if(!p || !out) return -1;
    for(int i=0;i<3;i++) if(!isfinite(p[i]) || p[i]<0 || p[i]>1) return -2;
    /* p[0] is positive coarse; p[1] is request; p[2] is threat. */
    const double scores[4]={p[0]*(1-p[1]),p[0]*p[1],(1-p[0])*(1-p[2]),(1-p[0])*p[2]};
    const char *labels[4]={"affiliative_relaxed","request_seeking","pain_distress","threat_discomfort"};
    int best=0;
    /* Stable tie order follows the listed class order, never random. */
    for(int i=1;i<4;i++) if(scores[i]>scores[best]) best=i;
    out->label=labels[best]; out->score=scores[best];
    return 0;
}
