var $ = jQuery.noConflict();

// remove tabindex from unclickable master details link
const removeMdTabIndex = function () {
	const mdLinks = $(".master_detail_column_btn");
	console.log("removing tab index");
	$.each(mdLinks, function (i, row) {
		console.log(row);
		$(row).attr("tabindex", null);
	});
};
//check if Master Details is used on this page
const checkMasterDetails = function () {
	const inputs = $("input");
	const mdBtnUsed = checkMdBtn();
	$.each(inputs, function (i, input) {
		if (input.defaultValue.includes("masterDetail") && !mdBtnUsed) {
			updateRows();
		}
	});
};

// check if Master Detail Button is also being used
const checkMdBtn = function () {
	const mdBtns = $(".master_detail_column_btn");
	if (mdBtns.length >= 1) {
		removeMdTabIndex();
		return true;
	}
};

// add tabindex + click  to all wpdt rows if MD is used but MD Button is not
const updateRows = function () {
	const rows = $("table.wpDataTable tr");

	$.each(rows, function (i, row) {
		$(row).attr("tabindex", 0);
	});

	const fireClick = function (event) {
		event.currentTarget.click();
	};

	$(rows).on("keypress", function (event) {
		if (event.which == 13) fireClick(event);
	});
};

checkMasterDetails();
// end of add tabindex + click to rows

//custom filtering on tables based on post tags - must wrap table and buttons group in caen-tags-filter class, use 'tags' as placeholder in the tags filter input in wpdt column filter setting as an ID cannot be placed at this time.
// $(document).ready(function () {
// 	const allTagBtns = $(".caen-tags-filter .wp-block-buttons a");
// 	allTagBtns.on("click", function (event) {
// 		const tagsInput = $(".caen-tags-filter input[placeholder='tags']");
// 		const $clickedTag = $(this);
// 		const selectedTag = $clickedTag.text();
//     console.log(tagsInput);

// 		if (selectedTag !== tagsInput.val()) {
// 			tagsInput.val(selectedTag);
// 		} else {
// 			tagsInput.val("");
// 			console.log("clear input val to blank");
// 		}

// 		toggleTagClass($clickedTag);
// 		triggerKeyUpEvent(tagsInput);
// 	});

// 	function toggleTagClass($selectedTag) {
// 		$selectedTag.toggleClass("tag-selected");
// 		console.log("Tag class toggled for selected tag.");
// 		$(".caen-tags-filter .wp-block-buttons a")
// 			.not($selectedTag)
// 			.removeClass("tag-selected");
// 	}

// 	function triggerKeyUpEvent($element) {
// 		const e = $.Event("keyup");
// 		$element.trigger(e);
// 		console.log("Triggered keyup event.");
// 	}
// });

$(document).ready(function () {
	const allCatBtns = $(".caen-cat-filter a");
	const select = $(".wp-block-query-filter-taxonomy select");
	const selectOpts = $(".wp-block-query-filter-taxonomy option");

	allCatBtns.on("click", function (event) {
		const $clickedTag = $(this);
		const clickedTagText = $clickedTag.text();
		let clickedTagPairOpt;

		//find value of option with same text as clickedtag
		$(selectOpts).each(function (i, opt) {
			if ($(opt).text() === clickedTagText) {
				clickedTagPairOpt = $(selectOpts[i]).val();
			}
		});

		// Was a new tag clicked?
		if (clickedTagPairOpt !== $(select).val()) {
			//update the select val
			$(selectOpts).each(function (i, option) {
				if (clickedTagText === option.textContent) {
					const newVal = $(option).val();
					$(select).val(newVal);
					triggerCatKeyUpEvent(select);
          	toggleTagClass($clickedTag);
				}
			});
		} else {
			console.log("same tag selected");
			//set tags back to 'all
			resetTagFilter();
      	toggleTagClass($clickedTag);
		}
	
	});

	function toggleTagClass($clickedTag) {
		console.log("Tag class toggled for selected tag.");
		$clickedTag.addClass("tag-selected");
		// $(allCatBtns).not($selectedTag).removeClass("tag-selected");
	}


	function resetTagFilter() {
		const resetVal = $(selectOpts[0]).val();
		$(select).val(resetVal);
		// $(allCatBtns).removeClass("tag-selected");
		// triggerCatKeyUpEvent(select);
	}

  	function triggerCatKeyUpEvent(select) {
			var $selectElement = select;
			var nativeSelect = $selectElement.get(0);
			if (nativeSelect) {
				nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));
			}
		}
});
