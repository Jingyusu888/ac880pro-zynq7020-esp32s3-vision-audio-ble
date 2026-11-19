/* PetLink 板端分类器接口（B09/B10 数值对齐契约） */
#ifndef PETLINK_CLASSIFIER_H
#define PETLINK_CLASSIFIER_H

#include "cat_model_params.h"

#ifndef CAT_MODEL_COUNT
#define CAT_MODEL_COUNT 3
#endif

/* 单模型推理：features[CAT_FEATURE_COUNT] -> P(classes_[1])；logit_out 可为 NULL */
float cat_model_probability(const float *features, int model_index, float *logit_out);

#endif /* PETLINK_CLASSIFIER_H */
