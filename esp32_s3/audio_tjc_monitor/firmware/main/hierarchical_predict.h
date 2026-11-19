#ifndef PL_PREDICT_H
#define PL_PREDICT_H
#include <stdbool.h>
typedef struct {
    const char *label;
    float confidence, margin;
    bool trigger;
    double probabilities[3];
} pl_prediction_t;
int pl_predict(const float features[238], pl_prediction_t *out);
int pl_decide_probabilities(const double probabilities[3], pl_prediction_t *out);
const char *pl_label_short(const char *label);
#endif
