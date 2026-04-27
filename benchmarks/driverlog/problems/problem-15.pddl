(define (problem dlog_light_15)
 (:domain dlog_3_3_3_problem_problem-domain)
 (:objects
   s0 s1 s2 s3 - location
   driver1 driver2 - driver
   truck1 truck2 - truck
   package1 package2 package3 - obj
 )
 (:init (at_ driver1 s0) (at_ driver2 s3) (at_ truck1 s0) (empty truck1) (at_ truck2 s2) (empty truck2) (at_ package1 s1) (at_ package2 s0) (at_ package3 s2) (link s0 s1) (link s1 s0) (link s1 s2) (link s2 s1) (link s2 s3) (link s3 s2) (path s0 s1) (path s1 s0) (path s1 s2) (path s2 s1) (path s2 s3) (path s3 s2))
 (:goal (and (at_ driver1 s3) (at_ package1 s2) (at_ package2 s3) (at_ package3 s0)))
)
