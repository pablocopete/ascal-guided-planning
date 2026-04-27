(define (problem dlog_light_06)
 (:domain dlog_3_3_3_problem_problem-domain)
 (:objects
   s0 s1 s2 s3 - location
   driver1 - driver
   truck1 - truck
   package1 package2 - obj
 )
 (:init (at_ driver1 s0) (at_ truck1 s0) (empty truck1) (at_ package1 s0) (at_ package2 s3) (link s0 s1) (link s1 s0) (link s1 s2) (link s2 s1) (link s2 s3) (link s3 s2) (path s0 s1) (path s1 s0) (path s1 s2) (path s2 s1) (path s2 s3) (path s3 s2))
 (:goal (and (at_ package1 s3) (at_ package2 s0)))
)
