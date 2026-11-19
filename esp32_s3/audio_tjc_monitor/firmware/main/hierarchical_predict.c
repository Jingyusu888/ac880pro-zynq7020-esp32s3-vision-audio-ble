#include "hierarchical_predict.h"
#include "classifier.h"
#include "model_thresholds.h"
#include <math.h>
#include <string.h>
int pl_decide_probabilities(const double p[3], pl_prediction_t *out) {
    if(!p || !out) return -1;
    for(int i=0;i<3;i++) if(!isfinite(p[i]) || p[i]<0 || p[i]>1) return -2;
    memcpy(out->probabilities,p,sizeof(out->probabilities));
    out->label="unknown"; out->trigger=false;
    double confidence=fmax(p[0],1-p[0]), margin=fabs(2*p[0]-1);
    if(confidence>=PL_COARSE_CONFIDENCE_THRESHOLD && margin>=PL_COARSE_MARGIN_THRESHOLD) {
        /* classes_[0] wins an exact .5 tie, as in Python argsort. */
        const char *coarse=coarse_classes[p[0]>.5];
        int branch=strcmp(coarse,"positive_or_request")==0 ? 1:2;
        const char *label=branch==1 ? positive_fine_classes[p[1]>.5] : negative_fine_classes[p[2]>.5];
        confidence=fmax(p[branch],1-p[branch]); margin=fabs(2*p[branch]-1);
        double conf_gate=PL_DEFAULT_FINE_CONFIDENCE_THRESHOLD, margin_gate=PL_DEFAULT_FINE_MARGIN_THRESHOLD;
        if(!strcmp(label,"request_seeking")) { conf_gate=PL_REQUEST_SEEKING_CONFIDENCE_THRESHOLD; margin_gate=PL_REQUEST_SEEKING_MARGIN_THRESHOLD; }
        if(!strcmp(label,"pain_distress")) { conf_gate=PL_PAIN_DISTRESS_CONFIDENCE_THRESHOLD; margin_gate=PL_PAIN_DISTRESS_MARGIN_THRESHOLD; }
        if(confidence>=conf_gate && margin>=margin_gate) { out->label=label; out->trigger=true; }
        else out->label=branch==1 ? "positive_or_request_uncertain":"negative_or_distress_uncertain";
    }
    out->confidence=(float)confidence; out->margin=(float)margin;
    return 0;
}
int pl_predict(const float features[238], pl_prediction_t *out) {
    if(!features || !out) return -1;
    float clean[238]; double p[3];
    for(int i=0;i<238;i++) clean[i]=isfinite(features[i]) ? features[i]:NAN;
    for(int i=0;i<3;i++) p[i]=cat_model_probability(clean,i,NULL);
    return pl_decide_probabilities(p,out);
}
const char *pl_label_short(const char *label) {
    if(!label) return "UNKNOWN";   /* 防御：NULL 时 strcmp 会解引用 0 地址导致 LoadProhibited */
    if(!strcmp(label,"affiliative_relaxed")) return "RELAX";
    if(!strcmp(label,"request_seeking")) return "REQUEST";
    if(!strcmp(label,"threat_discomfort")) return "THREAT";
    if(!strcmp(label,"pain_distress")) return "DISTRESS";
    if(!strcmp(label,"positive_or_request_uncertain")) return "POS UNC";
    if(!strcmp(label,"negative_or_distress_uncertain")) return "NEG UNC";
    /* 狗三分类（v6 任务书：狗结果不得显示 UNKNOWN） */
    if(!strcmp(label,"active"))  return "ACTIVE";
    if(!strcmp(label,"alert"))   return "ALERT";
    if(!strcmp(label,"rest"))    return "REST";
    return "UNKNOWN";
}
