(define (problem dlog_light_02)
 (:domain dlog_3_3_3_problem_problem-domain)
 (:objects
   s0 s1 s2 - location
   driver1 - driver
   truck1 - truck
   package1 - obj
 )
 (:init (at_ driver1 s0) (at_ truck1 s0) (empty truck1) (at_ package1 s0) (link s0 s1) (link s1 s0) (link s1 s2) (link s2 s1) (path s0 s1) (path s1 s0) (path s1 s2) (path s2 s1))
 (:goal (and (at_ package1 s2)))
)
