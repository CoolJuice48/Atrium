var $ = jQuery.noConflict();

//sunset genesis accordion
// closes all the other genesis accordions on the page when one is opened
const gbAccordions = $(".wp-block-genesis-blocks-gb-accordion");
const accDetails = $(".wp-block-genesis-blocks-gb-accordion details");

$(".wp-block-genesis-blocks-gb-accordion").on("click", function (event) {
	let targetI;
	// figure out which accordion was clicked on
	$.each(gbAccordions, function (i, val) {
		if (val == event.currentTarget) {
			targetI = i;
			return;
		}
	});
	// close all the accordions that are not the clicked on one
	$.each(accDetails, function (i, value) {
		if (i != targetI) {
			value.open = false;
		}
	});
});
// end of accordion closer

// newer wordpress 'details' block that acts as accordion
// note that within wpdt, details are sometimes loaded dynamically
$(document).on("click", "details", function (event) {
	const details = $(".wp-block-details");
	let targetI;

	// figure out which accordion was clicked on
	$.each(details, function (i, val) {
		if (val == event.currentTarget) {
			targetI = i;
			return;
		}
	});
	// close all the details that are not the clicked on one
	$.each(details, function (i, value) {
		if (i != targetI) {
			value.open = false;
		}
	});
});

// end of details closer
