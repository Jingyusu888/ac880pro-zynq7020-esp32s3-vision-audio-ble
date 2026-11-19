#ifndef PL_DEMO_CANDIDATE_H
#define PL_DEMO_CANDIDATE_H
typedef struct {
    const char *label;
    double score;
} pl_demo_candidate_t;
/* Display-only ranking; does not alter the frozen thresholded decision. */
int pl_demo_candidate(const double probabilities[3], pl_demo_candidate_t *out);
#endif
