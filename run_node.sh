#!/bin/bash
rm *.blockchain
for i in {0..4}
do
	python ./node.py -i $i -lf True &
	sleep 2
done


