#!/bin/bash
rm *.blockchain
for i in {0..16}
do
	python ./node.py -i $i -lf True &
	sleep 1
done


